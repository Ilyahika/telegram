"""Game data and equipment effects. Existing keys are retained during upgrades."""
AVATARS=['🎣','🐟','🐠','🦈','🐙','⚓','🚤','🦆','🐳','🦀','🦑','🐬','🐢','🦭','🪼','🐡','🦞','🦐','🪸','🐚','🌊','🏝️','🌙','🍀']
GROUPS={
'pond':'Плотва|Краснопёрка|Ротан|Верховка|Уклейка|Линь|Густера|Пескарь|Вьюн|Белый амур|Толстолобик|Серебряный карась|Зеркальный карп|Золотой линь|Янтарный окунь|Ночной сом|Императорский карп|Жемчужный карась|Древний сом|Король пруда',
'lake':'Ёрш|Елец|Подлещик|Синец|Белоглазка|Налим|Сиг|Ряпушка|Язь|Чехонь|Жерех|Озёрная форель|Озёрный голец|Серебряная щука|Чёрный судак|Северный сиг|Ледяной налим|Солнечная форель|Страж озера|Лунная белуга',
'sea':'Килька|Анчоус|Ставрида|Бычок|Барабуля|Сельдь|Камбала|Кефаль|Сарган|Морской окунь|Дорадо|Сибас|Палтус|Синий тунец|Красный луциан|Коралловый групер|Золотая дорада|Алая барракуда|Призрак рифа|Хранитель прилива',
'ocean':'Летучая рыба|Макрурус|Нототения|Морской лещ|Луфарь|Треска|Пикша|Сайда|Морской чёрт|Махи-махи|Ваху|Парусник|Жёлтопёрый тунец|Большая барракуда|Гигантский групер|Опах|Чёрный марлин|Огненная мурена|Король глубин|Астральная манта',
'stream':'Гольян|Быстрянка|Усатый голец|Речной бычок|Щиповка|Голавль|Речной пескарь|Кумжа|Ленок|Речная минога|Ручьевая форель|Серебряный хариус|Краснопёрый таймень|Радужная кумжа|Изумрудный голец|Звёздный ленок|Королевская форель|Лунный таймень|Дух течения|Сердце ручья',
}
BEHAVIORS=['calm','school','dart','bottom','predator']
BEHAVIOR_NAMES=dict(calm='Спокойная',school='Стайная',dart='Резкие рывки',bottom='Держится у дна',predator='Хищник')

# Функция expand: см. параметры, описание и вызовы ниже.
def expand(fish,gear,cases,tiers,locations):
    for loc in locations:
        for i,name in enumerate(GROUPS[loc['key']].split('|')):
            tier=0 if i<5 else 1 if i<10 else 2 if i<13 else 3 if i<16 else 4 if i<18 else 5 if i==18 else 6
            fish.append(dict(key=f"{loc['key']}_v5_{i}",name=name,location=loc['key'],rarity=tiers[tier],icon='🐠' if tier>=3 else '🐟',weight=[75,30,12,4,1,.2,.025][tier],value=int([12,30,65,150,400,1100,3000][tier]*(1+i*.025))))
    for i,f in enumerate(fish):
        tier=tiers.index(f['rarity']);f['weight']=[75,30,12,4,1,.2,.025][tier];f['behavior']=BEHAVIORS[(i+tier)%len(BEHAVIORS)];f['behavior_name']=BEHAVIOR_NAMES[f['behavior']]
        size=(.15+.22*(i%6))*(1+tier*.65)*(1.8 if f['location']=='ocean' else 1)
        xs=[0,112,218,323,428,533,639,748,857,979,1145];ys=[0,107,212,318,426,531,638,747,856,962,1069,1175,1283];x=i%10;y=i//10
        f['art']=dict(atlas='fish',index=i,cols=10,rows=12,rect=[xs[x],ys[y],xs[x+1]-xs[x],ys[y+1]-ys[y]],size=[1145,1374])
        f['min_kg']=round(size,2);f['max_kg']=round(size*(2.5+tier*.25),2)
    type_names=dict(rod=['Удочка «Тихий берег»','Спиннинг «Хищник»'],reel=['Катушка «Плавный ход»','Катушка «Турбо»'],line=['Леска «Эластик»','Плетёнка «Титан»'],bait=['Наживка «Глубина»','Приманка «Сияние»'],spoon=['Колебалка «Лист»','Колебалка «Волна»'],spinner=['Вертушка «Искра»','Вертушка «Вихрь»'])
    icons=dict(rod='🎣',reel='⚙️',line='🧵',bait='🪝',spoon='🥄',spinner='🌀')
    for typ,names in type_names.items():
        for tier,rar in enumerate(tiers):
            for variant,name in enumerate(names):
                gear.append(dict(key=f'v5_{typ}_{rar}_{variant}',type=typ,name=f'{name} {tier+1}',rarity=rar,icon=icons[typ],luck=0,price=0,variant=variant))
    for g in gear:
        t=tiers.index(g['rarity']);v=g.get('variant',0);k=g['type']
        stats={
         'rod':dict(control=.035+t*.013+v*.012,power=.06+t*.06,hook_window=.1+t*.04),
         'reel':dict(retrieve=.12+t*.09+v*.1,relief=.08+t*.065+(1-v)*.04),
         'line':dict(strength=3+2*t**1.7+v*1.5,elasticity=.08+t*.075+(1-v)*.04),
         'bait':dict(luck=.06+t*.13+v*.04,attraction=.1+t*.07,weight_bonus=.06+t*.03+(1-v)*.04),
         'spoon':dict(stability=.1+t*.075+(1-v)*.04,fatigue=.1+t*.08+v*.05),
         'spinner':dict(hook_window=.25+t*.12,find_luck=.06+t*.06,luck=.02+t*.03+v*.015)
        }[k]
        g['stats']=stats;g['consumable']=k in ['line','bait'];g['luck']=stats.get('luck',0)
        g['effect']={
         'rod':f"Зона +{stats.get('control',0):.0%} · контроль рывков",
         'reel':f"Подмотка +{stats.get('retrieve',0):.0%} · сброс натяжения",
         'line':f"До {stats.get('strength',0):.1f} кг · растяжимость {stats.get('elasticity',0):.0%}",
         'bait':f"Привлечение +{stats.get('attraction',0):.0%} · редкие уловы",
         'spoon':f"Рывки −{stats.get('stability',0):.0%} · утомляет рыбу",
         'spinner':f"Подсечка +{stats.get('hook_window',0):.2f} с · находки"
        }[k]
    lure_index=0
    for g in gear:
        if g['type'] in ['bait','spoon','spinner']:
            xs=[0,156,314,472,630,788,946,1103,1261];ys=[0,155,311,468,624,780,935,1084,1247];x=lure_index%8;y=lure_index//8
            g['art']=dict(atlas='lure',index=lure_index,cols=8,rows=8,rect=[xs[x],ys[y],xs[x+1]-xs[x],ys[y+1]-ys[y]],size=[1261,1247]);lure_index+=1
    distributions=[[68,20,9,2.6,.35,.045,.005],[30,35,23,10,1.8,.18,.02],[10,23,35,26,5.4,.55,.05],[2,8,25,42,20,2.7,.3]]
    for case,distribution in zip(cases,distributions):
        counts={r:sum(g['rarity']==r for g in gear) for r in tiers}
        case.update(items=[g['key'] for g in gear],weights=[distribution[tiers.index(g['rarity'])]/counts[g['rarity']] for g in gear])
