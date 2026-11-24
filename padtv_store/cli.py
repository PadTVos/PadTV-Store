"""Small JSON interface consumed asynchronously by any Store frontend."""
import argparse
import json
import subprocess
import sys
from .catalog import load
from .providers import FlatpakProvider, GooglePlayProvider, status
from .github import GitHubProvider

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'install', 'remove'])
    parser.add_argument('app_id', nargs='?')
    args = parser.parse_args()
    try:
        products = load()
        if args.action == 'status':
            result = status(products)
        else:
            if not sys.platform.startswith('linux'):
                raise RuntimeError('Instalace je dostupná pouze v PadTV OS.')
            product = next((p for p in products if p.id == args.app_id), None)
            if not product or not product.installable or product.kind not in ('flatpak', 'android', 'padbridge'):
                raise ValueError('Tuto aplikaci nelze instalovat tímto poskytovatelem.')
            provider = GitHubProvider() if product.kind == 'padbridge' else GooglePlayProvider() if product.kind == 'android' else FlatpakProvider()
            result = {'id': product.id, **(getattr(provider, args.action)(product) or {})}
        print(json.dumps({'ok': True, **result}), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error)}), flush=True)
        return 1

if __name__ == '__main__':
    sys.exit(main())
