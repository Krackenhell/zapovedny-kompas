"""Build the catalogue from reviewed Nominatim responses and region polygons.
Usage: python build_regions.py OBSERVATIONS REGIONS BASE OUTPUT
Requires shapely==2.1.2 for topology checks (not required by the app/updater).
"""
import json,sys
from pathlib import Path
from shapely.geometry import shape,mapping
from shapely import make_valid
from shapely.ops import unary_union


def polygonal(g):
    if not g.is_valid:g=make_valid(g)
    if g.geom_type=='GeometryCollection':g=unary_union([x for x in g.geoms if x.geom_type in ('Polygon','MultiPolygon')])
    return g if g.geom_type in ('Polygon','MultiPolygon') and not g.is_empty else None


def build(observations,regions,base):
    region_shapes={r['id']:shape(r['geometry']) for r in regions}
    # Explicitly reviewed exception: tagged as a park in OSM, legal status confirmed separately.
    reviewed={'relation/19621078':{'name':'Памятник природы «Лесопарк Затюменский»',
        'reference':'https://tyumedia.ru/295793.html','title':'Пресс-центр Управления Росреестра по Тюменской области: природоохранные территории'}}
    zones={}
    for result in observations:
        for item in result['data']:
            sid=item['osm_type']+'/'+str(item['osm_id'])
            tags=item.get('extratags') or {}
            protected=item['type'] in ('protected_area','nature_reserve','national_park') or tags.get('boundary') in ('protected_area','national_park')
            if not protected and sid not in reviewed:continue
            if not item.get('name') or item.get('geojson',{}).get('type') not in ('Polygon','MultiPolygon'):continue
            geom=polygonal(shape(item['geojson']))
            if geom is None:continue
            ids=[rid for rid,rg in region_shapes.items() if geom.intersection(rg).area>max(1e-9,geom.area*.001)]
            if not ids:continue
            # Regional boundary intersections prevent same-name places in other regions entering the catalogue.
            z={'id':'osm-'+sid.replace('/','-'),'name':item['name'],'region_ids':ids,
                'precise':False,'catalog_import':True,'kind':tags.get('protection_title','Охраняемая природная территория (по OSM)'),
                'area':'площадь по официальному реестру уточняется','regime':{'published':False,'verification':'not_reviewed'},
                'source':{'title':'Контур OpenStreetMap, проверка каталога 25.10.2026','url':'https://www.openstreetmap.org/'+sid},
                'note':'Справочный контур OpenStreetMap; юридическая граница и действующий режим требуют сверки с реестром ООПТ. Каталог неполный.',
                'geometry':mapping(geom),'osm_id':sid}
            if sid in reviewed:
                r=reviewed[sid];z['name']=r['name'];z['references']=[{'title':r['title'],'url':r['reference']}]
                z['note']='Контур лесопарка по OpenStreetMap, а не кадастровая граница памятника природы. Статус ООПТ подтверждён публикацией Росреестра; правила в приложении ещё не проверены.'
            zones[sid]=z
    # One reserve with two named sections, rather than two different reserves.
    crane=[k for k,z in zones.items() if 'Журавлиная родина' in z['name']]
    if len(crane)>1:
        members=[zones.pop(k) for k in crane];combined=members[0]
        combined['id']='osm-crane-homeland';combined['name']='Заказник «Журавлиная родина»'
        combined['geometry']=mapping(unary_union([shape(z['geometry']) for z in members]))
        combined['references']=[z['source'] for z in members[1:]]
        zones['crane-homeland']=combined
    original=[]
    for z in base['zones']:
        if z.get('catalog_import'):continue
        z['region_ids']=['tyumen'];original.append(z)
    result={**base,'regions':regions,'catalog_updated':'2026-10-25','catalog_complete':False,
        'attribution':'© OpenStreetMap contributors, ODbL 1.0','zones':original+sorted(zones.values(),key=lambda z:z['name'])}
    return result

if __name__=='__main__':
    observations,regions,base=[json.loads(Path(p).read_text(encoding='utf-8')) for p in sys.argv[1:4]]
    data=build(observations,regions,base)
    Path(sys.argv[4]).write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    for r in data['regions']:print(r['id'],sum(r['id'] in z['region_ids'] for z in data['zones']))
