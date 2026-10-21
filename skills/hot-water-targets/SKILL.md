---
name: hot-water-targets
description: Asked about the hot water tank target, solar heating, or to change the tank temperature.
roles: [home]
---
1. Read the current tank state with `ha_state` on the water heater entity: target and current temperature.
2. Targets used here: 50 C by day. 55 C when today's solar forecast is 10 kWh or more, because the tank
   then stores free solar heat. Overnight 45 C, or 42 C when tomorrow's solar forecast is 10 kWh or more.
3. The allowed range is 35 to 60 C. The anti legionella cycle belongs to the device. Do not try to change it.
4. To change the target, follow the approval-requests skill with `set_hot_water_target`. Put the current target
   and the forecast in the reason.
5. If the requested value equals the current target, say there is nothing to change.
