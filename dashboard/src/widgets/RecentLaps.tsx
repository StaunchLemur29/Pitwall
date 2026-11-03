import { delta, lapTime, prettyName } from "../lib/format";
import { useRig } from "../lib/rig";
import { Card } from "./common";

export function RecentLaps() {
  const laps = useRig((s) => s.laps);
  const session = useRig((s) => s.session);
  const valid = laps.filter((l) => l.valid);
  const best = valid.length ? Math.min(...valid.map((l) => l.lap_time_ms)) : null;
  const sectorCount = Math.max(0, ...laps.map((l) => l.sector_ms.length));
  const bestSectors = Array.from({ length: sectorCount }, (_, i) =>
    Math.min(...valid.filter((l) => l.sector_ms.length === sectorCount).map((l) => l.sector_ms[i])),
  );

  return (
    <Card title={session ? prettyName(session.car) : "Laps"} right={`${valid.length} valid / ${laps.length}`}>
      {laps.length === 0 ? (
        <div className="upcoming">No laps yet for this car and track.</div>
      ) : (
        <div className="rlaps">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Time</th>
                <th>Δ best</th>
                {bestSectors.map((_, i) => (
                  <th key={i}>S{i + 1}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {laps.map((l) => (
                <tr key={l.id} className={`${!l.valid ? "rlaps--invalid" : ""} ${l.lap_time_ms === best && l.valid ? "rlaps--best" : ""}`}>
                  <td>{l.lap_number}</td>
                  <td>
                    {lapTime(l.lap_time_ms)}
                    {l.out_lap && <span className="tag">out</span>}
                    {!l.valid && !l.out_lap && <span className="tag tag--bad">cut</span>}
                  </td>
                  <td>{best && l.valid ? (l.lap_time_ms === best ? "—" : delta((l.lap_time_ms - best) / 1000, 3)) : ""}</td>
                  {bestSectors.map((bs, i) => (
                    <td key={i} className={l.valid && l.sector_ms[i] === bs ? "rlaps--purple" : ""}>
                      {l.sector_ms[i] ? (l.sector_ms[i] / 1000).toFixed(2) : ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
