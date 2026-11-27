"""Pinned GitHub Release APK downloads; installation is delegated to PadBridge.

The packaged catalog is the trust root. Remote content cannot supply a new hash
or signer. TLS, bounded downloads, SHA-256 and APK signature checks all precede
installation. No downloaded shell scripts or privileged installers are run.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .catalog import validate
from .providers import run

HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def allowed(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError('Stahování opustilo povolené HTTPS servery GitHubu.')


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubProvider:
    def __init__(self, opener=None):
        self.opener = opener or build_opener(ReleaseRedirect())

    def call(self, *args):
        reply = json.loads(run(['padbridge', *args], 240))
        if not reply.get('ok'):
            raise RuntimeError(reply.get('error', 'PadBridge neodpověděl.'))
        return reply

    def inventory(self):
        return self.call('list')['apps']

    def download(self, product, target):
        validate(product)
        if (product.source, product.kind) != ('github', 'padbridge'):
            raise ValueError('Neplatná aplikace GitHub.')
        allowed(product.download_url)
        digest = hashlib.sha256()
        size = 0
        deadline = time.monotonic() + 180
        request = Request(product.download_url, headers={'User-Agent': 'PadTV-Store/0.7', 'Accept': 'application/octet-stream'})
        with self.opener.open(request, timeout=20) as response, Path(target).open('xb') as output:
            allowed(response.geturl())
            while True:
                if time.monotonic() > deadline:
                    raise RuntimeError('Vypršel čas stahování.')
                block = response.read(64 * 1024)
                if not block:
                    break
                size += len(block)
                if size > product.download_size:
                    raise ValueError('Stažený soubor překročil schválenou velikost.')
                digest.update(block)
                output.write(block)
        if size != product.download_size or digest.hexdigest() != product.sha256:
            raise ValueError('Nesouhlasí velikost nebo SHA-256 staženého APK.')

    def install(self, product):
        with tempfile.TemporaryDirectory(prefix='padtv-github-') as folder:
            apk = Path(folder) / 'release.apk'
            self.download(product, apk)
            meta = self.call('inspect', str(apk))['app']
            if meta['package'] != product.target or meta['sha256'] != product.sha256 or meta['signers'] != [product.signer_sha256]:
                raise ValueError('Identita nebo ověřený podpis APK neodpovídá katalogu.')
            reply = self.call('install', str(apk))
            installed = next((a for a in self.inventory() if a['package'] == product.target), None)
            if not installed or installed['sha256'] != product.sha256:
                raise RuntimeError('Instalaci stažené aplikace se nepodařilo ověřit.')
            return {'app': reply['app'], 'source': product.download_url}

    def remove(self, product):
        validate(product)
        if (product.source, product.kind) != ('github', 'padbridge'):
            raise ValueError('Neplatná aplikace GitHub.')
        self.call('remove', product.target)  # User data retained, as with local APK.
        if any(a['package'] == product.target for a in self.inventory()):
            raise RuntimeError('Aplikace je stále nainstalovaná.')
