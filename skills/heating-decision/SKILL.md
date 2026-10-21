---
name: heating-decision
description: Asked whether to switch the heat pump to Winter or back to Summer, or whether it will be cold.
roles: [home]
---
The house has underfloor heating, which reacts slowly, so the switch is made a day ahead.
1. Read the current preset with `ha_state` on the heat pump entity.
2. Call `weather_forecast` for at least 3 days.
3. Rule for Winter: a night of 4 C or colder in the next 2 days, or tomorrow's average (high plus low,
   divided by 2) of 7 C or lower. Otherwise stay in Summer.
4. If the preset is already Winter and the next 5 days average 15 C or more, say it may be time for
   Summer. This is advice only.
5. If the rule says switch and the preset is Summer, follow the approval-requests skill with
   `set_heating_preset` and preset `Winter`. If the rule says no, say so with the numbers. When a person
   explicitly asks for the change and the forecast clearly does not justify it, explain why and ask them
   to confirm in a new request. Do not file it yourself.
6. Quote the numbers you used (lowest night, tomorrow's average, current preset). Never say the heating was changed.
