import json,time,urllib.request,urllib.parse
from pathlib import Path
out=Path('region-downloads');out.mkdir(exist_ok=True)
for rid,iso in [('tyumen','RU-TYU'),('moscow','RU-MOW'),('moscow-oblast','RU-MOS')]:
    query='[out:json][timeout:120];area["ISO3166-2"="'+iso+'"]["boundary"="administrative"]->.a;(way(area.a)["boundary"~"^(protected_area|national_park)$"];relation(area.a)["boundary"~"^(protected_area|national_park)$"];way(area.a)["leisure"="nature_reserve"];relation(area.a)["leisure"="nature_reserve"];);out geom;'
    for host in ['https://overpass-api.de/api/interpreter','https://overpass.private.coffee/api/interpreter','https://maps.mail.ru/osm/tools/overpass/api/interpreter']:
        try:
            req=urllib.request.Request(host,data=urllib.parse.urlencode({'data':query}).encode(),headers={'User-Agent':'ZapovednyKompas/1.0 (https://github.com/Krackenhell/zapovedny-kompas)'})
            with urllib.request.urlopen(req,timeout=150) as response:raw=response.read()
            data=json.loads(raw)
            if data.get('remark') or not data.get('elements'):raise ValueError('Incomplete response')
            (out/(rid+'-osm.json')).write_bytes(raw)
            print(rid,len(data['elements']),flush=True)
            break
        except Exception as e:print(rid,type(e).__name__,flush=True)
    else:raise SystemExit('Could not download '+rid)
    time.sleep(3)
