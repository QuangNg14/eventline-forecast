use super::replay::{Window, HOUR};
use std::fmt::Write;

// Fixed-width arithmetic and integer-only sampling make the fixture portable.
struct Rng(u64);

impl Rng {
    fn below(&mut self, n: u64) -> u64 {
        self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        (self.0 >> 32) % n
    }
}

pub fn generate() -> String {
    let start = 1_736_121_600; // Monday 2025-01-06 00:00 UTC
    let end = start + 42 * 24 * HOUR;
    let window = Window { start, end, lateness: 2 * HOUR, through: end };
    let mut rng = Rng(173);
    let mut rows = Vec::new();
    let mut sequence = 0;
    let mut level = 0i64;
    for hour in 0..42 * 24 {
        level = (level + rng.below(5) as i64 - 2).clamp(-5, 5);
        let weekday = hour / 24 % 7 < 5;
        let peak = 12 - (hour as i64 % 24 - 14).abs();
        let count = if hour % 211 == 77 { 0 } else {
            (10 + peak + if weekday { 4 } else { 0 } + level).max(0)
        };
        for _ in 0..count {
            sequence += 1;
            let occurred = start + hour * HOUR + rng.below(HOUR);
            let delay = if rng.below(5) == 0 { rng.below(window.lateness + 1) } else { rng.below(301) };
            let available = occurred + delay;
            let units = 1 + rng.below(3);
            if available <= window.through {
                rows.push(format!(" EVT-{sequence} ,{occurred},{available},{units:02}"));
                if sequence % 9 == 0 && available + 90 <= window.through {
                    rows.push(format!("evt-{sequence},{occurred},{},{units}", available + 90));
                }
            }
        }
    }
    for i in (1..rows.len()).rev() {
        rows.swap(i, rng.below(i as u64 + 1) as usize);
    }
    let mut output = window.header();
    for row in rows { writeln!(output, "{row}").unwrap(); }
    output
}
