mod replay;
mod synthetic;

use std::{env, fs, process};

fn run(args: &[String]) -> Result<(), String> {
    match args {
        [cmd, output] if cmd == "generate" => {
            fs::write(output, synthetic::generate()).map_err(|e| format!("{output}: {e}"))
        }
        [cmd, input, output] if cmd == "replay" => {
            let text = fs::read_to_string(input).map_err(|e| format!("{input}: {e}"))?;
            let (canonical, rows, unique) = replay::normalize(&text)?;
            fs::write(output, canonical).map_err(|e| format!("{output}: {e}"))?;
            eprintln!("{rows} deliveries, {unique} events, {} retries", rows - unique);
            Ok(())
        }
        _ => Err("usage: ingest generate OUTPUT | ingest replay INPUT OUTPUT".into()),
    }
}

fn main() {
    if let Err(err) = run(&env::args().skip(1).collect::<Vec<_>>()) {
        eprintln!("ingest: {err}");
        process::exit(1);
    }
}
