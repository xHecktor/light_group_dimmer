"""
Reine, Home-Assistant-unabhängige Helligkeitsmathematik für die gewichtete
Gruppendimmung.

Bewusst ohne HA-Importe, damit die Kernlogik isoliert (unit-)testbar ist und
gegen die realen Hue-Referenzwerte abgeglichen werden kann.
"""


def compute_target_brightnesses(lamp_brightnesses, target_group_brightness):
    """
    Berechnet für alle aktiven (dimmbaren) Lampen die neue Helligkeit, sodass der
    Mittelwert der Gruppe genau target_group_brightness trifft.

    Alle Werte im Home-Assistant-Bereich 0..255.

    Gewichtung:
      - beim Hochdimmen bekommen dunklere Lampen mehr Zuwachs (mehr "Headroom"),
      - beim Runterdimmen geben hellere Lampen mehr ab.

    Der Zielwert wird in einem Schritt exakt getroffen. Nur wenn Lampen an 0/255
    anschlagen, wird der Restanteil auf die verbleibenden Lampen umverteilt
    (höchstens so oft wie Lampen saturieren). Lampen ohne Helligkeit (Wert 0,
    z. B. Steckdosen / On-Off-Geräte) werden ignoriert.
    """
    active = {lp: float(v) for lp, v in lamp_brightnesses.items() if v and v > 0}
    if not active:
        return {}

    n = len(active)
    target_sum = target_group_brightness * n
    result = dict(active)
    locked = set()

    # Maximal n+1 Durchgänge – jeder Durchgang fixiert mindestens eine saturierte Lampe.
    for _ in range(n + 1):
        free = [lp for lp in result if lp not in locked]
        if not free:
            break

        delta_total = target_sum - sum(result.values())
        if abs(delta_total) < 0.5:
            break

        dimming_up = delta_total > 0
        weights = {
            lp: (1.0 - result[lp] / 255.0) if dimming_up else (result[lp] / 255.0)
            for lp in free
        }
        total_weight = sum(weights.values())
        if total_weight <= 1e-9:
            break

        scaling = delta_total / total_weight
        newly_locked = False
        for lp in free:
            new_val = result[lp] + weights[lp] * scaling
            if new_val <= 0:
                new_val = 0.0
                locked.add(lp)
                newly_locked = True
            elif new_val >= 255:
                new_val = 255.0
                locked.add(lp)
                newly_locked = True
            result[lp] = new_val

        # Keine neue Saturierung => Ziel ist (bis auf Rundung) erreicht.
        if not newly_locked:
            break

    return {lp: int(round(v)) for lp, v in result.items()}
