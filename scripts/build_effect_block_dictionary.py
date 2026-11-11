"""Build the local full-pool effect-block dictionary; no models or engine calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ygo_kito.effect_blocks import build_dictionary
from ygo_kito.effect_mechanisms import MechanismCatalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True,help='Existing native asset root; read only')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    cdb=args.assets/'engine-src/database/locales/zh-CN/cards.cdb'
    receipt=json.loads((args.assets/'engine-build/receipt.json').read_text(encoding='utf-8'))
    # Source-bound construction assessments require the actual pinned CDB.
    with cdb.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=receipt['resources']['cards']:raise ValueError('card database differs from asset receipt')
    with sqlite3.connect(cdb.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows={r['id']:dict(r) for r in db.execute('select d.*,t.name,t.desc from datas d join texts t on d.id=t.id')}
    catalog=MechanismCatalog(SimpleNamespace(rows=rows,receipt=receipt))
    manifest=build_dictionary(catalog,args.output,source={'cards':str(cdb.resolve()),'database_commit':receipt['source_commits']['database']})
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='unresolved_effects'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
