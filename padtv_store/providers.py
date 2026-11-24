"""Provider boundaries. Unprivileged Flatpak; APT belongs to System Core."""
import os
import json
import subprocess
import sys
from .catalog import validate

FLATHUB = 'https://dl.flathub.org/repo/flathub.flatpakrepo'


class GooglePlayProvider:
    """Delegate to the installed Android adapter; never download unofficial APKs."""
    def call(self, action, package=None):
        reply = json.loads(run(['padtv-android', action] + ([package] if package else []), 240))
        if not reply.get('ok'):
            raise RuntimeError(reply.get('error', 'Android neodpověděl.'))
        return reply

    def inventory(self):
        return self.call('inventory')

    def install(self, product):
        validate(product)
        if (product.source, product.kind) != ('google-play', 'android'):
            raise ValueError('Neplatná aplikace Google Play.')
        return self.call('play', product.target)

    def remove(self, product):
        validate(product)
        if (product.source, product.kind) != ('google-play', 'android'):
            raise ValueError('Neplatná aplikace Google Play.')
        return self.call('remove', product.target)

def run(argv, timeout=1800):
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, env={**os.environ, 'LC_ALL': 'C.UTF-8'})
    if result.returncode:
        raise RuntimeError(result.stdout[-1500:].strip() or 'Správce aplikací operaci odmítl.')
    return result.stdout

class FlatpakProvider:
    def installed(self):
        return set(run(['flatpak', 'list', '--user', '--app', '--columns=application'], 30).splitlines())

    def install(self, product):
        validate(product)
        if (product.source, product.kind) != ('flathub', 'flatpak'):
            raise ValueError('Tento zdroj není povolen pro Flatpak.')
        run(['flatpak', 'remote-add', '--user', '--if-not-exists', 'flathub', FLATHUB], 120)
        # A conflicting user remote must not silently impersonate Flathub.
        remotes = run(['flatpak', 'remotes', '--user', '--columns=name,url'], 30)
        if not any(line.split() == ['flathub', 'https://dl.flathub.org/repo/'] for line in remotes.splitlines()):
            raise RuntimeError('Zdroj flathub má jinou adresu. Zkontrolujte jeho konfiguraci.')
        run(['flatpak', 'install', '--user', '--noninteractive', '--assumeyes', 'flathub', product.target])
        if product.target not in self.installed():
            raise RuntimeError('Instalaci aplikace se nepodařilo ověřit.')

    def remove(self, product):
        validate(product)
        if product.kind != 'flatpak' or product.source != 'flathub':
            raise ValueError('Neplatná aplikace Flatpak.')
        if product.target in run(['flatpak', 'ps', '--columns=application'], 15).splitlines():
            raise RuntimeError('Před odinstalováním aplikaci zavřete.')
        run(['flatpak', 'uninstall', '--user', '--noninteractive', '--assumeyes', '--delete-data', product.target])
        if product.target in self.installed():
            raise RuntimeError('Aplikace je stále nainstalovaná.')

def status(products):
    if not sys.platform.startswith('linux'):
        return {'flatpak': [], 'apt': [], 'error': 'Instalace linuxových aplikací je dostupná v PadTV OS.'}
    result = {'flatpak': [], 'apt': [], 'android': [], 'android_known': False, 'error': ''}
    try:
        from .github import GitHubProvider
        bridge = GitHubProvider().inventory()
        result.update(padbridge=[a['package'] for a in bridge], padbridge_apps=bridge, padbridge_known=True)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result.update(padbridge=[], padbridge_known=False, padbridge_error=str(error))
    try:
        android = GooglePlayProvider().inventory()
        result.update(android=android.get('packages', []), android_known=android.get('known', False),
                      google_play=android.get('google_play', False), android_initialized=android.get('initialized', False))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        result['android_error'] = str(error)
    try:
        result['flatpak'] = sorted(FlatpakProvider().installed())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        result['error'] = str(error)
    for p in products:
        if p.kind == 'apt':
            query = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}', p.target],
                                   capture_output=True, text=True, timeout=10)
            if query.returncode == 0 and query.stdout == 'installed':
                result['apt'].append(p.target)
    return result
