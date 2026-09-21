//! spool — append-only archive capture for axiom-mine.
//!
//! Subscribes to the hub's broadcast channel and appends every event (plus
//! lifecycle markers) to NDJSON segment files on local disk. This is the raw,
//! immutable capture path; the Redis Streams fan-out is unchanged.
//!
//! Env-gated: active only when `AXIOM_SPOOL_DIR` is set.

use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use tokio::sync::{broadcast, mpsc};
use tracing::{error, info, warn};

const MAX_SEGMENT_BYTES: u64 = 256 * 1024 * 1024; // 256 MB
const FSYNC_INTERVAL_MS: u64 = 200;
const FSYNC_EVENT_COUNT: u64 = 1000;
const LAG_WATERMARK: u64 = 100_000;

static SPOOL_ACTIVE: AtomicBool = AtomicBool::new(false);
static SPOOL_QUEUED: AtomicU64 = AtomicU64::new(0);

pub fn is_active() -> bool { SPOOL_ACTIVE.load(Ordering::Relaxed) }
pub fn queued() -> u64 { SPOOL_QUEUED.load(Ordering::Relaxed) }

fn utc_now_rfc3339() -> String { chrono::Utc::now().to_rfc3339() }

/// WIB = UTC+7, no DST.
fn wib_date_str() -> String {
    (chrono::Utc::now() + chrono::Duration::hours(7)).format("%Y-%m-%d").to_string()
}

/// Build a lifecycle marker line. Also used by tests.
pub fn lifecycle_line(event: &str, detail: serde_json::Value) -> String {
    serde_json::json!({
        "kind": "lifecycle",
        "symbol": "",
        "ts": utc_now_rfc3339(),
        "payload": { "event": event, "detail": detail }
    })
    .to_string()
}

struct SegmentWriter {
    dir: PathBuf,
    date: String,
    index: u64,
    file: Option<BufWriter<File>>,
    active_path: PathBuf,
    bytes: u64,
    events_since_sync: u64,
    last_sync: std::time::Instant,
}

impl SegmentWriter {
    fn new(root: &Path) -> std::io::Result<Self> {
        let mut w = Self {
            dir: root.to_path_buf(),
            date: String::new(),
            index: 0,
            file: None,
            active_path: PathBuf::new(),
            bytes: 0,
            events_since_sync: 0,
            last_sync: std::time::Instant::now(),
        };
        w.rotate(true)?;
        Ok(w)
    }

    fn day_dir(&self) -> PathBuf { self.dir.join(&self.date) }
    fn sealed_path(&self, index: u64) -> PathBuf {
        self.day_dir().join(format!("events-{:05}.ndjson", index))
    }
    fn active_path(&self, index: u64) -> PathBuf {
        self.day_dir().join(format!("events-{:05}.ndjson.active", index))
    }

    fn rotate(&mut self, force: bool) -> std::io::Result<()> {
        let today = wib_date_str();
        let day_changed = today != self.date;
        let too_big = self.bytes >= MAX_SEGMENT_BYTES;
        if !force && !day_changed && !too_big {
            return Ok(());
        }
        // Seal current segment.
        if let Some(mut f) = self.file.take() {
            let _ = f.flush();
            let _ = f.get_ref().sync_all();
            let sealed = self.sealed_path(self.index);
            if let Err(e) = std::fs::rename(&self.active_path, &sealed) {
                warn!("spool: failed to seal {:?}: {}", self.active_path, e);
            } else {
                info!("spool: sealed {:?} ({} bytes)", sealed, self.bytes);
            }
        }
        if day_changed {
            self.date = today;
            self.index = 0;
            std::fs::create_dir_all(self.day_dir())?;
        }
        self.index += 1;
        self.active_path = self.active_path(self.index);
        let file = OpenOptions::new().create(true).append(true).open(&self.active_path)?;
        self.file = Some(BufWriter::new(file));
        self.bytes = 0;
        self.events_since_sync = 0;
        self.last_sync = std::time::Instant::now();
        Ok(())
    }

    fn write_line(&mut self, line: &str) -> std::io::Result<()> {
        self.rotate(false)?;
        let f = match self.file.as_mut() { Some(f) => f, None => return Ok(()) };
        f.write_all(line.as_bytes())?;
        f.write_all(b"\n")?;
        self.bytes += line.len() as u64 + 1;
        self.events_since_sync += 1;
        // High-rate batches sync on a byte/count threshold; low-rate streams
        // are flushed by the periodic tick in the writer loop.
        if self.events_since_sync >= FSYNC_EVENT_COUNT {
            f.flush()?;
            let _ = f.get_ref().sync_all();
            self.events_since_sync = 0;
            self.last_sync = std::time::Instant::now();
        }
        Ok(())
    }

    /// Flush buffered data to disk if we've crossed the time threshold.
    /// Called by the writer loop's periodic ticker so idle periods still durably
    /// persist the few events that arrived (weekends, pre-open, low-volume names).
    fn flush_due(&mut self) -> std::io::Result<()> {
        if self.events_since_sync == 0 {
            return Ok(());
        }
        if self.last_sync.elapsed().as_millis() as u64 >= FSYNC_INTERVAL_MS {
            if let Some(f) = self.file.as_mut() {
                f.flush()?;
                let _ = f.get_ref().sync_all();
            }
            self.events_since_sync = 0;
            self.last_sync = std::time::Instant::now();
        }
        Ok(())
    }
}

/// Handle handed to main for emitting lifecycle events.
#[derive(Clone)]
pub struct SpoolHandle {
    pub tx: Option<mpsc::UnboundedSender<String>>,
}

impl SpoolHandle {
    pub fn inactive() -> Self { Self { tx: None } }
    pub fn lifecycle(&self, event: &str, detail: serde_json::Value) {
        if let Some(tx) = &self.tx {
            let _ = tx.send(lifecycle_line(event, detail));
        }
    }
}

/// Spawn the spool subscriber + writer. Returns a handle for lifecycle events.
pub fn spawn(hub_tx: broadcast::Sender<String>) -> Option<SpoolHandle> {
    let dir = std::env::var("AXIOM_SPOOL_DIR").ok()?;
    if dir.trim().is_empty() { return None; }
    let root = PathBuf::from(dir);
    if let Err(e) = std::fs::create_dir_all(&root) {
        error!("spool: cannot create {:?}: {} — spool disabled", root, e);
        return None;
    }

    let (tx, mut rx) = mpsc::unbounded_channel::<String>();
    let mut sub_rx = hub_tx.subscribe();

    // Subscriber: move events off the bounded broadcast channel ASAP.
    let lag_tx = tx.clone();
    tokio::spawn(async move {
        loop {
            match sub_rx.recv().await {
                Ok(msg) => {
                    let q = SPOOL_QUEUED.fetch_add(1, Ordering::Relaxed) + 1;
                    if q == LAG_WATERMARK {
                        let _ = lag_tx.send(lifecycle_line("spool_lag", serde_json::json!({ "queued": q })));
                        warn!("spool: {} events queued — writer falling behind", q);
                    }
                    if lag_tx.send(msg).is_err() { break; }
                }
                Err(broadcast::error::RecvError::Lagged(n)) => {
                    warn!("spool: broadcast lagged {} — data may be lost", n);
                    let _ = lag_tx.send(lifecycle_line("broadcast_lag", serde_json::json!({ "dropped": n })));
                }
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    });

    // Writer: drains the queue and periodically flushes so idle periods persist.
    let root_clone = root.clone();
    info!("spool: archiving to {:?}", root_clone);
    tokio::spawn(async move {
        let mut writer = match SegmentWriter::new(&root_clone) {
            Ok(w) => w,
            Err(e) => { error!("spool: writer init failed: {}", e); return; }
        };
        let mut flush_tick = tokio::time::interval(std::time::Duration::from_millis(FSYNC_INTERVAL_MS));
        flush_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            tokio::select! {
                maybe = rx.recv() => {
                    match maybe {
                        Some(line) => {
                            SPOOL_QUEUED.fetch_sub(1, Ordering::Relaxed);
                            if let Err(e) = writer.write_line(&line) {
                                error!("spool: write failed: {}", e);
                            }
                        }
                        None => break, // channel closed
                    }
                }
                _ = flush_tick.tick() => {
                    if let Err(e) = writer.flush_due() {
                        error!("spool: flush failed: {}", e);
                    }
                }
            }
        }
        let _ = writer.rotate(true);
        info!("spool: writer shut down");
    });

    SPOOL_ACTIVE.store(true, Ordering::Relaxed);
    Some(SpoolHandle { tx: Some(tx) })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lifecycle_line_shape() {
        let line = lifecycle_line("capture_start", serde_json::json!({"watchlist": ["BBCA"]}));
        let v: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(v["kind"], "lifecycle");
        assert_eq!(v["payload"]["event"], "capture_start");
        assert!(v["ts"].as_str().unwrap().contains('T'));
    }

    #[test]
    fn test_wib_date_is_valid() {
        let d = wib_date_str();
        assert_eq!(d.len(), 10);
        assert_eq!(&d[4..5], "-");
    }

    #[test]
    fn test_segment_rotation_and_sealing() {
        let tmp = std::env::temp_dir().join(format!("spool_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let mut w = SegmentWriter::new(&tmp).unwrap();
        for i in 0..5 {
            w.write_line(&format!("{{\"n\":{}}}", i)).unwrap();
        }
        w.rotate(true).unwrap();
        let day = wib_date_str();
        let sealed = tmp.join(&day).join("events-00001.ndjson");
        assert!(sealed.exists(), "sealed segment should exist");
        let active = tmp.join(&day).join("events-00002.ndjson.active");
        assert!(active.exists(), "new active segment should exist");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn test_flush_due_persists_single_low_volume_event() {
        // Reproduces the weekend/pre-open case: one event, then silence.
        let tmp = std::env::temp_dir().join(format!("spool_flush_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let mut w = SegmentWriter::new(&tmp).unwrap();
        w.write_line("{\"kind\":\"lifecycle\",\"event\":\"capture_start\"}").unwrap();

        // Force the time threshold to have elapsed, then the periodic tick fires.
        w.last_sync = std::time::Instant::now() - std::time::Duration::from_millis(FSYNC_INTERVAL_MS + 10);
        w.flush_due().unwrap();

        let day = wib_date_str();
        let active = tmp.join(&day).join("events-00001.ndjson.active");
        let contents = std::fs::read_to_string(&active).unwrap();
        assert!(contents.contains("capture_start"), "event must be durably flushed, got: {:?}", contents);
        let _ = std::fs::remove_dir_all(&tmp);
    }
}

