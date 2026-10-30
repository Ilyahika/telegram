"""Automatic, server-timed catch. Controls cannot alter outcomes or skip time."""
# Функция loadout: см. параметры, описание и вызовы ниже.
def loadout(equipment,catalog):
    return {'luck':sum(min(.15,max(0,catalog.get(k,{}).get('luck',0))) for slot,k in equipment.items() if slot in ('rod','reel','tackle'))}
# Функция create_battle: см. параметры, описание и вызовы ниже.
def create_battle(fish,kg,equipment,stats,seed,uid,now,tier):
    return dict(version=11,id=uid,fish=fish,kg=kg,equipment=equipment,stats=stats,seed=seed,tier=tier,started=now,duration=[3.5,4,5,6,7.5,9,10][tier],sequence=-1,phase='fight',progress=0,done=False,won=False)
# Функция advance: см. параметры, описание и вызовы ниже.
def advance(b,now,position,reeling,hook,sequence):
    b['progress']=min(100,max(0,(now-b['started'])/b['duration']*100))
    if b['progress']>=100:b.update(done=True,won=True)
    return b
# Функция target_at: см. параметры, описание и вызовы ниже.
def target_at(b,t=None):return .5
