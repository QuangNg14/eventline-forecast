use std::collections::{btree_map::Entry, BTreeMap};
use std::fmt::Write;

pub const COLUMNS: &str = "event_id,occurred_at,available_at,units";
pub const VERSION: &str = "eventline-v1";
pub const HOUR: u64 = 3600;

pub struct Window {
    pub start: u64,
    pub end: u64,
    pub lateness: u64,
    pub through: u64,
}

impl Window {
    pub fn header(&self) -> String {
        format!("{VERSION},{},{},{},{}\n{COLUMNS}\n", self.start, self.end, self.lateness, self.through)
    }

    fn parse(line: &str) -> Result<Self, String> {
        let fields: Vec<_> = line.split(',').map(str::trim).collect();
        let [VERSION, start, end, delay, through] = fields.as_slice() else {
            return Err("expected eventline-v1,start,end,max_lateness,observed_through".into());
        };
        let w = Window {
            start: number(start)?, end: number(end)?, lateness: number(delay)?, through: number(through)?,
        };
        if w.start >= w.end || w.start % HOUR != 0 || w.end % HOUR != 0 || w.through < w.start {
            return Err("invalid observation window or snapshot time".into());
        }
        Ok(w)
    }
}

fn number(raw: &str) -> Result<u64, String> {
    if raw.is_empty() || !raw.bytes().all(|c| c.is_ascii_digit()) {
        return Err("expected unsigned decimal integer".into());
    }
    raw.parse().map_err(|_| "integer too large".into())
}

#[derive(Debug)]
struct Fact {
    occurred: u64,
    available: u64,
    units: u64,
}

fn delivery(line: &str, w: &Window) -> Result<(String, Fact), String> {
    let fields: Vec<_> = line.split(',').map(str::trim).collect();
    let [id, occurred, available, units] = fields.as_slice() else {
        return Err("expected four event columns".into());
    };
    if id.is_empty() || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_') {
        return Err("invalid event ID".into());
    }
    let fact = Fact { occurred: number(occurred)?, available: number(available)?, units: number(units)? };
    if !(w.start..w.end).contains(&fact.occurred) || !(fact.occurred..=w.through).contains(&fact.available) {
        return Err("occurrence or delivery outside observation contract".into());
    }
    if !(1..=u32::MAX as u64).contains(&fact.units) {
        return Err("units must be a positive uint32".into());
    }
    Ok((id.to_ascii_lowercase(), fact))
}

pub fn normalize(text: &str) -> Result<(String, usize, usize), String> {
    let mut lines = text.lines();
    let window = Window::parse(lines.next().unwrap_or(""))?;
    if lines.next() != Some(COLUMNS) {
        return Err("unexpected event columns".into());
    }
    let mut events = BTreeMap::<String, Fact>::new();
    let mut rows = 0;
    for (i, line) in lines.enumerate() {
        let (id, fact) = delivery(line, &window).map_err(|e| format!("line {}: {e}", i + 3))?;
        match events.entry(id) {
            Entry::Vacant(slot) => { slot.insert(fact); }
            Entry::Occupied(mut slot) => {
                let prior = slot.get_mut();
                if prior.occurred != fact.occurred || prior.units != fact.units {
                    return Err(format!("line {}: conflicting payload for {}", i + 3, slot.key()));
                }
                prior.available = prior.available.min(fact.available);
            }
        }
        rows += 1;
    }
    // The delivery guarantee is for the first receipt of an ID, not its retries.
    let mut ordered: Vec<_> = events.into_iter().collect();
    ordered.sort_unstable_by(|(a, x), (b, y)| (x.available, x.occurred, a).cmp(&(y.available, y.occurred, b)));
    let mut output = window.header();
    for (id, f) in &ordered {
        if f.available - f.occurred > window.lateness {
            return Err(format!("first delivery exceeds maximum lateness: {id}"));
        }
        writeln!(output, "{id},{},{},{}", f.occurred, f.available, f.units).unwrap();
    }
    Ok((output, rows, ordered.len()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot(rows: &str) -> String {
        Window { start: 0, end: 7200, lateness: 60, through: 7200 }.header() + rows
    }

    #[test]
    fn retries_keep_first_receipt_regardless_of_order() {
        let a = " X-1 ,001,100,02\n";
        let b = "x-1,1,5,2\n";
        let c = "Y,2,3,1\n";
        let expected = snapshot("y,2,3,1\nx-1,1,5,2\n");
        for rows in [[a, b, c], [c, b, a]] {
            assert_eq!(normalize(&snapshot(&rows.concat())).unwrap(), (expected.clone(), 3, 2));
        }
        assert_eq!(normalize(&expected).unwrap().0, expected);
    }

    #[test]
    fn conflicts_are_errors_in_either_order() {
        for other in ["Q,1,3,2\n", "q,2,3,1\n"] {
            for rows in [["q,1,2,1\n", other], [other, "q,1,2,1\n"]] {
                assert!(normalize(&snapshot(&rows.concat())).unwrap_err().contains("conflicting"));
            }
        }
    }

    #[test]
    fn rejects_invalid_deliveries_and_windows() {
        for row in ["a,1,0,1", "a,1,62,1", "a,7200,7200,1", "a,7199,7201,1",
                    "a,0,0,0", "a,0,0,4294967296", "a,0,0,-1", "a,0,0", "a b,0,0,1"] {
            assert!(normalize(&snapshot(row)).is_err(), "{row}");
        }
        for input in [snapshot("").replace("v1", "v0"), snapshot("").replace(",7200,", ",7201,"),
                      snapshot("").replace("event_id", "id")] {
            assert!(normalize(&input).is_err());
        }
    }
}
