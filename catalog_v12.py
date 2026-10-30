"""Species keyed photographic cutouts; saved assets, no runtime external requests."""
import json
from pathlib import Path
_MANIFEST=json.loads((Path(__file__).parent/'assets'/'fish_manifest_v12.json').read_text(encoding='utf-8'))
# Функция apply_art: см. параметры, описание и вызовы ниже.
def apply_art(fish):
    for item in fish:
        art=dict(_MANIFEST[item['key']])
        if art.pop('name')!=item['name']:raise ValueError('Fish image/name mismatch: '+item['key'])
        item['art']=art
