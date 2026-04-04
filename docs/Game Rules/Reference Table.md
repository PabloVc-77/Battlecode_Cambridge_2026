Estadísticas de Entidades


  ┌────────────────┬─────┬──────────────┬───────────────────┬───────────────────────────────────────────────┐
  │ Entidad        │ HP  │ Coste Base   │ Aumento de Escala │ Notas                                         │
  ├────────────────┼─────┼──────────────┼───────────────────┼───────────────────────────────────────────────┤
  │ Core           │ 500 │ —            │ —                 │ 3x3; spawnea builders                         │
  │ Builder bot    │ 30  │ 30 Ti        │ +20%              │ Móvil; construye, cura, ataca, destruye       │
  │ Conveyor       │ 20  │ 3 Ti         │ +1%               │ 3 entradas, 1 salida                          │
  │ Splitter       │ 20  │ 6 Ti         │ +1%               │ 1 entrada, 3 salidas rotativas                │
  │ Bridge         │ 20  │ 20 Ti        │ +10%              │ Salida a casilla dentro de dist 3             │
  │ Armoured conv. │ 50  │ 5 Ti, 5 Ax   │ +1%               │ Cinta con más HP                              │
  │ Harvester      │ 30  │ 20 Ti        │ +5%               │ Produce cada 4 rondas                         │
  │ Foundry        │ 50  │ 40 Ti        │ +100%             │ Ti + Ax crudo → Ax refinado                   │
  │ Road           │ 5   │ 1 Ti         │ +0.5%             │ Transitable                                   │
  │ Barrier        │ 30  │ 3 Ti         │ +1%               │ Bloquea el paso                               │
  │ Marker         │ 1   │ Gratis       │ —                 │ Sin cooldown de acción                        │
  │ Gunner         │ 40  │ 10 Ti        │ +10%              │ Rayo frontal; muros bloquean; girable (10 Ti) │
  │ Sentinel       │ 30  │ 30 Ti        │ +20%              │ Línea ±1; Ax refinado aturde (+5 cd)          │
  │ Breach         │ 60  │ 15 Ti, 10 Ax │ +10%              │ Cono 180°; fuego amigo                        │
  │ Launcher       │ 30  │ 20 Ti        │ +10%              │ Lanza builders adyacentes                     │
  └────────────────┴─────┴──────────────┴───────────────────┴───────────────────────────────────────────────┘

  Estadísticas de Combate


  ┌─────────────┬────────────────┬────────────────┬────────────────┬─────────────────┬─────────┬───────────────┐       
  │ Unidad      │ Visión ($r^2$) │ Acción ($r^2$) │ Ataque ($r^2$) │ Daño            │ Recarga │ Munición/Tiro │       
  ├─────────────┼────────────────┼────────────────┼────────────────┼─────────────────┼─────────┼───────────────┤       
  │ Core        │ 36             │ 8              │ —              │ —               │ —       │ —             │       
  │ Builder bot │ 20             │ 2              │ 0 (propia)     │ 2               │ —       │ 2 Ti          │       
  │ Gunner      │ 13             │ 2              │ 13             │ 10 (30 con Ax)  │ 1       │ 2             │       
  │ Sentinel    │ 32             │ 2              │ 32             │ 18              │ 3       │ 10            │       
  │ Breach      │ 13             │ 2              │ 5              │ 40 (+20 splash) │ 1       │ 5             │       
  │ Launcher    │ 26             │ 2 (recoger)    │ 26 (lanzar)    │ —               │ 1       │ —             │       
  └─────────────┴────────────────┴────────────────┴────────────────┴─────────────────┴─────────┴───────────────┘       

  Constantes del Juego


  ┌───────────────────────┬─────────────────────────────────────────────────────────────┐
  │ Constante             │ Valor                                                       │
  ├───────────────────────┼─────────────────────────────────────────────────────────────┤
  │ Rondas Máximas        │ 2000                                                        │
  │ Límite de Unidades    │ 50 unidades vivas por equipo (incluye el Core)              │
  │ Tamaño de Stack       │ 10                                                          │
  │ Titanium Inicial      │ 500                                                         │
  │ Axionite Inicial      │ 0                                                           │
  │ Ingreso Pasivo (Ti)   │ 10 cada 4 rondas                                            │
  │ Cura de Builder       │ 4 HP por 1 Ti a todos los aliados en casilla ($r^2 \le 2$)  │
  │ Ataque de Builder     │ 2 daño por 2 Ti (solo en su propia casilla)                 │
  │ Salida de Harvester   │ Cada 4 rondas                                               │
  │ Aturdimiento Sentinel │ +5 de cooldown a acción y movimiento (Munición Ax refinada) │
  │ Tiempo de CPU         │ 2ms por unidad/ronda (+5% buffer)                           │
  │ Límite de Memoria     │ 1 GB por bot                                                │
  └───────────────────────┴─────────────────────────────────────────────────────────────┘

  Escalado de Costes

  El coste de cada entidad aumenta de forma aditiva según las unidades que ya tengas:
  $$\text{coste final} = \lfloor \text{escala total} \times \text{coste base} \rfloor$$

   * +0.5%: Road
   * +1%: Conveyor, Splitter, Armoured conveyor, Barrier