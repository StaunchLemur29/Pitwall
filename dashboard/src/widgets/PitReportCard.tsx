/** In the pits: how the stint went, one glance. Mistakes that kept happening
 * first, then what the stint did to the car, then one thing for the next stint. */
import type { PitReport } from "../lib/types";

export function PitReportCard({ r }: { r: PitReport }) {
  const times = [
    r.best && `best ${r.best}${r.new_pb ? " (new PB)" : ""}`,
    r.typical && r.clean_laps > 1 && `typical ${r.typical}`,
    r.spread_s != null && `±${r.spread_s.toFixed(2)} s`,
  ].filter(Boolean);
  const moments = r.repeats.length ? r.repeats.map((x) => x.text) : r.worst.map((x) => `${x.label}: ${x.text}`);
  return (
    <section className="pitrep" aria-label="Pit report">
      <div className="pitrep__head">
        <span className="coach__tag">Pit report</span>
        <b>
          {r.laps} lap{r.laps === 1 ? "" : "s"}
          {r.clean_laps !== r.laps ? `, ${r.clean_laps} clean` : ""}
        </b>
        {times.length > 0 && <span className="muted"> · {times.join(" · ")}</span>}
        {r.race?.position ? <span className="muted"> · P{r.race.position}</span> : null}
      </div>
      {moments.length > 0 && (
        <div>
          <div className="pitrep__sub">{r.repeats.length ? "Kept happening" : "This stint"}</div>
          <ul>
            {moments.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      {r.car.length > 0 && (
        <div>
          <div className="pitrep__sub">The car</div>
          <ul>
            {r.car.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      {r.setup && r.setup.length > 0 && (
        <div>
          <div className="pitrep__sub">Settings to try</div>
          <ul>
            {r.setup.map((a) => (
              <li key={a.title}>
                <b>{a.do}</b> <span className="muted">{a.title}.</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.next && (
        <div className="pitrep__next">
          <b>Next stint:</b> {r.next}
        </div>
      )}
    </section>
  );
}
