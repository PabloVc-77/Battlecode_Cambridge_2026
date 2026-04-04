# 🛠️ Actualización de Doctrina: Operaciones Titan (v1.5.1)

Debido a las fluctuaciones del mercado y las regulaciones de seguridad, Meridian Industries ha implementado cambios en la logística, reparación y protocolos de armas. 

## 📊 Economía y Reglas Globales
* **Límite de Unidades:** Máximo de **50 unidades** por equipo.
* **Titanio Inicial:** Reducido a **500 Ti**.
* **Ingresos Pasivos:** Se obtienen **10 Ti** cada 4 turnos.
* **Axionite Bruto (Raw Axionite):** Se destruye automáticamente si se entrega al núcleo o a las torretas sin refinar.
* **Conversión en el Núcleo:** Los núcleos ahora pueden convertir Axionite en Titanio usando `convert(amount: int)`.
  * **Tasa de conversión:** 1 Ax = 4 Ti.
  * El Ax convertido se resta de las estadísticas de "Ax recolectado" y se suma a las de "Ti recolectado".

## 🤖 Unidades

### Builder Bots
* **Costo:** 30 Ti.
* **Escalado de costo:** Añaden un **20%** de escalado.
* **Autodestrucción:** Se ha eliminado el daño por autodestrucción.
* **Ataque:** Cuesta 2 Ti infligir 2 de daño (solo pueden atacar la casilla en la que están parados).
* **Curación:** Cuesta 1 Ti curar 4 HP. Pueden curar dentro de su radio de acción completo (ya no están limitados a su propia casilla).

### Sentinels
* **Costo:** 30 Ti.
* **Escalado de costo:** Añaden un **20%** de escalado.
* **Disparo:** 10 de daño por disparo, consumiendo 10 de munición.
* **Recarga:** 3 rondas.
* **Munición de Axionite:** El aturdimiento (*stun*) dura **5 turnos**.

### Gunners
* **Daño:** La munición de Axionite ahora inflige **30 de daño**.
* **Línea de Visión (LOS):** Los edificios transitables bloquean su línea de visión, pero **pueden disparar a través de los marcadores**.
* **Movilidad:** Pueden rotar en **cualquier dirección** usando `rotate(direction)`.
  * **Costo:** 10 Ti del almacén global.
  * **Enfriamiento:** 1 turno.

## 🏗️ Estructuras e Infraestructura

* **Breach:** Costo reducido a **15 Ti**. El radio de visión² se incrementó a **13**.
* **Harvester:** Costo reducido a **20 Ti**. Añade un **5%** de escalado.
* **Bridges (Puentes):** Costo de **20 Ti**. Añaden un **10%** de escalado.
* **Foundry:** Costo reducido a **40 Ti**.
* **Ax Conveyor:** Costo reducido a **5 Ti**.
* **Roads (Caminos):** Salud reducida a **5 HP**.

## ⚔️ Mecánicas de Combate y Correcciones
* **Prioridad de Impacto:** Si hay un Builder Bot sobre un edificio, todos los ataques de las torretas impactarán **únicamente** al Builder Bot.
* **Corrección de Error:** Ya no es posible colocar una baldosa no transitable debajo de un Builder Bot enemigo/aliado.

## 💻 Actualizaciones de Sistema y API (CLI v1.5.1)
La herramienta CLI ha sido renovada. Ahora es posible nombrar las entregas (*submissions*) y alternar entre las versiones antiguas. Se han añadido los siguientes métodos a la API:

* `get_attackable_tiles()`: Obtiene el patrón de ataque de una torreta.
* `get_attackable_tiles_from(position, direction, turret_type)`: Permite testear el alcance desde una posición hipotética.
* `can_fire_from(position, direction, turret_type, target)`: Permite comprobar si una torreta hipotética podría disparar a un objetivo.
* `can_rotate(direction)`: Comprueba si un Gunner tiene la capacidad de rotar.