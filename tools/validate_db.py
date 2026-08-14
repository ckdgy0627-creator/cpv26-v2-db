#!/usr/bin/env python3
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'catalog.json'
PLAYERS = ROOT / 'players.json'
OUT = ROOT / 'research' / 'db_validation_latest.json'
VALID_HITTER_POSITIONS = {'C','1B','2B','3B','SS','LF','CF','RF','DH'}
VALID_VERIFICATION = {'OFFICIAL','IN_GAME_SCREENSHOT','VERIFIED','REFERENCE',''}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(s):
    return re.sub(r"[\s\-\.\'·]", '', str(s or '')).lower()


def as_date(s):
    return date.fromisoformat(s)


def main():
    errors=[]; warnings=[]
    catalog=load(CATALOG); players=load(PLAYERS)
    if catalog.get('schemaVersion') != 1: errors.append('catalog schemaVersion != 1')
    if players.get('schemaVersion') != 1: errors.append('players schemaVersion != 1')
    if catalog.get('playersSha256') != sha(PLAYERS): errors.append('players SHA256 mismatch')

    entries={e['cardSetId']:e for e in catalog.get('cardSets',[])}
    active_id=catalog.get('activeCardSetId')
    if active_id not in entries: errors.append('activeCardSetId missing from cardSets')

    all_player_ids=set()
    for p in players.get('records',[]):
        if not p.get('koreanName'): errors.append('blank koreanName in players')
        pid=p.get('playerId')
        if pid:
            if pid in all_player_ids: errors.append(f'duplicate playerId: {pid}')
            all_player_ids.add(pid)

    card_reports=[]
    for card_id,entry in entries.items():
        rel = 'cards/' + card_id.lower() + '.json'
        path = ROOT / rel
        if not path.exists():
            errors.append(f'missing card file: {rel}')
            continue
        raw_sha=sha(path)
        if entry.get('sha256') != raw_sha: errors.append(f'{card_id}: SHA256 mismatch')
        card=load(path)
        for field in ('cardSetId','cardSetLabel','dbVersion','liveUpdateNo','effectiveFrom','effectiveTo'):
            if card.get(field) != entry.get(field): errors.append(f'{card_id}: catalog/card {field} mismatch')
        start=as_date(card['effectiveFrom']); end=as_date(card['effectiveTo']) if card.get('effectiveTo') else None
        groups=defaultdict(list)
        current=[]
        for i,r in enumerate(card.get('records',[])):
            name=r.get('playerName',''); team=r.get('team',''); pos=r.get('position','')
            if not name: errors.append(f'{card_id}[{i}]: blank playerName')
            if pos not in VALID_HITTER_POSITIONS: errors.append(f'{card_id}/{team}/{name}: invalid hitter position={pos}')
            rf=as_date(r['effectiveFrom']); rt=as_date(r['effectiveTo']) if r.get('effectiveTo') else None
            if rf < start: errors.append(f'{card_id}/{team}/{name}: record starts before card set')
            if end and rf > end: errors.append(f'{card_id}/{team}/{name}: record starts after card set end')
            if rt and rt < rf: errors.append(f'{card_id}/{team}/{name}: invalid effective interval')
            if int(r.get('liveUpdateNo',0)) > int(card.get('liveUpdateNo',0)): errors.append(f'{card_id}/{team}/{name}: record Live update exceeds package')
            verification=str(r.get('verification','')).upper()
            if verification not in VALID_VERIFICATION: errors.append(f'{card_id}/{team}/{name}: invalid verification={verification}')
            if r.get('verified'):
                if not team: errors.append(f'{card_id}/{name}: verified record missing team')
                if not str(r.get('sourceUrl','')).startswith('https://'): errors.append(f'{card_id}/{team}/{name}: verified record missing https source')
            key=(norm(team), norm(name))
            groups[key].append((rf,rt,name,team,pos))
            today=date.today()
            if rf <= today and (rt is None or today <= rt): current.append(r)

        for key,history in groups.items():
            history.sort(key=lambda x:x[0])
            for a,b in zip(history,history[1:]):
                a_end=a[1] or date.max
                if a_end >= b[0]: errors.append(f'{card_id}/{a[3]}/{a[2]}: overlapping position history')

        active_keys=defaultdict(list)
        for r in current:
            active_keys[(norm(r.get('team')),norm(r.get('playerName'))) ].append(r)
        for key,recs in active_keys.items():
            if len(recs)>1: errors.append(f'{card_id}: multiple current records for {key}: {len(recs)}')

        card_reports.append({
            'cardSetId':card_id,
            'recordCount':len(card.get('records',[])),
            'currentHitterCardCount':len(active_keys),
            'currentVerifiedCount':sum(1 for recs in active_keys.values() if recs[0].get('verified')),
            'currentOfficialCount':sum(1 for recs in active_keys.values() if str(recs[0].get('verification','')).upper()=='OFFICIAL' or ('verification' not in recs[0] and 'cpbv-community.com2us.com' in str(recs[0].get('sourceUrl','')))),
            'currentInGameCount':sum(1 for recs in active_keys.values() if str(recs[0].get('verification','')).upper()=='IN_GAME_SCREENSHOT'),
            'sha256':raw_sha,
        })

    observation=catalog.get('gameCatalogObservation') or {}
    observed_total=int(observation.get('totalCardCount') or 0)
    active_report=next((x for x in card_reports if x['cardSetId']==active_id),None)
    if observed_total and active_report and active_report['currentHitterCardCount'] > observed_total:
        errors.append('current hitter count exceeds observed total in-game cards')
    if not observed_total: warnings.append('no gameCatalogObservation.totalCardCount yet')

    report={
        'ok': not errors,
        'catalogVersion': catalog.get('catalogVersion'),
        'revision': catalog.get('revision'),
        'activeCardSetId': active_id,
        'playerMasterCount': len(players.get('records',[])),
        'observedGameTotalCards': observed_total or None,
        'observedAt': observation.get('observedAt'),
        'cardSets': card_reports,
        'errors': errors,
        'warnings': warnings,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)

if __name__ == '__main__':
    main()
