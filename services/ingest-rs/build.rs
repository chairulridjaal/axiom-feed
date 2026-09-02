fn main() -> Result<(), Box<dyn std::error::Error>> {
    // graceful fallback when protoc not installed (CI without apt)
    let protoc = std::env::var("PROTOC").ok();
    let has_protoc = if let Some(p) = protoc {
        std::path::Path::new(&p).exists()
    } else {
        // try `protoc --version` via which
        std::process::Command::new("protoc")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    };
    if !has_protoc {
        eprintln!("cargo:warning=protoc not found — using pre-generated stub (run `make proto` with protoc for full build)");
        // ensure OUT_DIR has stub so include! doesn't fail
        let out = std::env::var("OUT_DIR").unwrap();
        let stub = r#"#[allow(dead_code, clippy::all)]
            // stub generated when protoc unavailable — minimal structs for compilation
            pub mod stockbit {
                pub mod datafeed {
                    pub mod v1 {}
                }
            }
            #[derive(Clone, PartialEq, ::prost::Message)]
            pub struct WebsocketWrapMessageChannel { #[prost(oneof="websocket_wrap_message_channel::MessageChannel", tags="1,2,6,8,9,10")] pub message_channel: Option<websocket_wrap_message_channel::MessageChannel> }
            pub mod websocket_wrap_message_channel { #[derive(Clone, PartialEq, ::prost::Oneof)] pub enum MessageChannel { #[prost(message, tag="1")] RunningTrade(super::RunningTrade), #[prost(message, tag="2")] Ping(super::PingResponse), #[prost(message, tag="6")] OrderbookBody(super::OrderBookBody), #[prost(message, tag="8")] RunningTradeBatch(super::RunningTradeBatch), #[prost(message, tag="9")] Liveprice(super::LivePrice), #[prost(message, tag="10")] Orderbook(super::Orderbook) } }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct RunningTrade { #[prost(string, tag="2")] pub stock: String, #[prost(double, tag="3")] pub price: f64, #[prost(double, tag="4")] pub volume: f64, #[prost(enumeration="TradeType", tag="5")] pub action: i32, #[prost(bool, tag="6")] pub is_global: bool, #[prost(message, optional, tag="7")] pub time: Option<::prost_types::Timestamp>, #[prost(message, optional, tag="8")] pub change: Option<Change>, #[prost(int64, tag="9")] pub trade_number: i64, #[prost(enumeration="BoardType", tag="10")] pub market_board: i32, #[prost(message, optional, tag="1")] pub websocket_time: Option<::prost_types::Timestamp> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct RunningTradeBatch { #[prost(message, repeated, tag="1")] pub trades: Vec<RunningTrade> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct LivePrice { #[prost(string, tag="1")] pub stock: String, #[prost(double, tag="2")] pub price: f64, #[prost(double, tag="3")] pub volume: f64, #[prost(double, tag="4")] pub high: f64, #[prost(double, tag="5")] pub low: f64, #[prost(double, tag="6")] pub prev_close: f64, #[prost(double, tag="7")] pub frequency: f64, #[prost(double, tag="10")] pub average: f64, #[prost(string, tag="11")] pub time_str: String, #[prost(double, tag="12")] pub open: f64, #[prost(double, tag="13")] pub close_indicator: f64, #[prost(double, tag="14")] pub value: f64, #[prost(bytes, tag="15")] pub change_data: Vec<u8>, #[prost(string, tag="16")] pub extra: String, #[prost(int32, tag="17")] pub is_index: i32 }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct Orderbook { #[prost(string, tag="1")] pub stock: String, #[prost(string, tag="2")] pub body: String, #[prost(int64, tag="3")] pub sequence: i64, #[prost(int64, tag="4")] pub depth: i64, #[prost(string, tag="5")] pub time: String, #[prost(int32, tag="8")] pub type_flag: i32, #[prost(string, tag="9")] pub server_time: String }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct OrderBookBody { #[prost(string, tag="1")] pub stock_symbol: String, #[prost(message, repeated, tag="2")] pub bid: Vec<Bid>, #[prost(message, repeated, tag="3")] pub offer: Vec<Offer>, #[prost(message, optional, tag="4")] pub time: Option<::prost_types::Timestamp> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct Bid { #[prost(double, tag="1")] pub price: f64, #[prost(double, tag="2")] pub lot: f64 }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct Offer { #[prost(double, tag="1")] pub price: f64, #[prost(double, tag="2")] pub lot: f64 }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct Change { #[prost(double, tag="1")] pub value: f64, #[prost(double, tag="2")] pub percentage: f64 }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct PingResponse { #[prost(message, optional, tag="1")] pub timestamp: Option<::prost_types::Timestamp> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct WebsocketChannel { #[prost(string, repeated, tag="1")] pub watchlist: Vec<String>, #[prost(string, repeated, tag="2")] pub order_book: Vec<String>, #[prost(string, repeated, tag="3")] pub running_trade: Vec<String>, #[prost(string, repeated, tag="5")] pub running_trade_batch: Vec<String>, #[prost(string, repeated, tag="6")] pub liveprice: Vec<String>, #[prost(string, repeated, tag="7")] pub orderbook_body: Vec<String> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct WebsocketRequest { #[prost(string, tag="1")] pub user_id: String, #[prost(message, optional, tag="2")] pub channel: Option<WebsocketChannel>, #[prost(string, tag="3")] pub key: String, #[prost(message, optional, tag="4")] pub ping: Option<PingRequest> }
            #[derive(Clone, PartialEq, ::prost::Message)] pub struct PingRequest { #[prost(message, optional, tag="1")] pub timestamp: Option<::prost_types::Timestamp> }
            #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)] #[repr(i32)] pub enum TradeType { Unspecified = 0, Buy = 1, Sell = 2 }
            #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, ::prost::Enumeration)] #[repr(i32)] pub enum BoardType { Unspecified = 0, Rg = 1, Tn = 2, Ng = 3 }
        "#;
        std::fs::write(format!("{}/stockbit.datafeed.v1.rs", out), stub).unwrap();
        return Ok(());
    }
    for (proto, inc) in [
        ("proto/datafeed.proto", "proto"),
        ("../../shared/proto/datafeed.proto", "../../shared/proto"),
    ] {
        if std::path::Path::new(proto).exists() {
            prost_build::compile_protos(&[proto], &[inc])?;
            return Ok(());
        }
    }
    prost_build::compile_protos(&["proto/datafeed.proto"], &["proto"])?;
    Ok(())
}
