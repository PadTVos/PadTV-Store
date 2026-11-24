"""Strict, versioned catalog. Catalog entries are data, never shell commands."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SOURCES = {'web': 'Web Apps', 'flathub': 'Flathub', 'apt': 'Debian APT',
           'github': 'GitHub', 'padtv': 'PadTV Repository', 'google-play': 'Google Play'}
ID = re.compile(r'[a-zA-Z][a-zA-Z0-9_.-]{0,127}\Z')
FLATPAK = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_-]*){2,}\Z')
APT = re.compile(r'[a-z0-9][a-z0-9+.-]+\Z')
ANDROID = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\Z')

@dataclass(frozen=True)
class Product:
    id: str
    title: str
    kind: str
    target: str
    source: str
    category: str
    description: str
    symbol: str = 'apps'
    color: str = '#e5eff5'
    compatibility: str = ''

    @property
    def installable(self):
        # Remote community / GitHub executable distribution requires a signed,
        # explicitly configured repository; do not trust arbitrary catalog URLs.
        return (self.source, self.kind) in {('web', 'web'), ('flathub', 'flatpak'), ('google-play', 'android')}

def validate(product):
    if not ID.fullmatch(product.id) or not product.title.strip() or len(product.title) > 120:
        raise ValueError('Neplatná identita aplikace v katalogu.')
    if product.source not in SOURCES or len(product.description) > 2000:
        raise ValueError('Neplatný zdroj aplikace.')
    if not isinstance(product.compatibility,str) or len(product.compatibility)>2000:
        raise ValueError('Neplatný popis kompatibility.')
    if product.kind == 'web':
        url = urlsplit(product.target)
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Webová aplikace v katalogu musí mít HTTPS adresu.')
    elif product.kind == 'flatpak':
        if not FLATPAK.fullmatch(product.target):
            raise ValueError('Neplatný identifikátor Flatpak.')
    elif product.kind == 'apt':
        if product.source != 'apt' or not APT.fullmatch(product.target):
            raise ValueError('Neplatný systémový balíček.')
    elif product.kind == 'android':
        if product.source != 'google-play' or not ANDROID.fullmatch(product.target):
            raise ValueError('Neplatná aplikace Google Play.')
    else:
        raise ValueError('Nepodporovaný formát aplikace.')
    if (product.source == 'web' and product.kind != 'web'
            or product.source == 'flathub' and product.kind != 'flatpak'
            or product.source == 'google-play' and product.kind != 'android'):
        raise ValueError('Zdroj neodpovídá formátu aplikace.')
    return product

def load(path=None):
    path = Path(path) if path else Path(__file__).resolve().parent.parent / 'catalog' / 'apps.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('apps'), list):
        raise ValueError('Nepodporovaná verze katalogu.')
    products = [validate(Product(**item)) for item in data['apps']]
    if len({p.id for p in products}) != len(products):
        raise ValueError('Katalog obsahuje duplicitní aplikace.')
    return products
