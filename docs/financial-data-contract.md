# Financial data contract

The production dashboard uses the configured TeaJoin provider as its
authoritative daily source.  Provider rows are normalized before they enter
the calculation layer:

- prices are yuan; volume is lots; daily amount is yuan;
- daily rows must contain `symbol`, `date`, OHLCV and `amount`, with unique
  `(symbol, date)` keys and valid OHLC ranges;
- TeaJoin `pct_chg`, `amplitude` and `turnover_rate` are converted from
  percentage points to the internal decimal representation;
- `daily_basic` market values reported in ten-thousand yuan and share counts
  reported in ten-thousand shares are converted to yuan and shares for AI
  financial analysis;
- the AI financial analysis reads the local cache first and requests the
  configured TeaJoin symbol history when the local table has no rows;
- the exchange `calendar` dataset supplies open dates for A-share cutoffs.

The calendar is cached in memory for six hours.  A refresh is rejected when it
does not cover the current date and at least the preceding seven calendar days;
dates outside the verified window use the weekday fallback rather than being
silently treated as holidays.  A refresh failure retains the last verified
calendar and does not fall back to another vendor's rows.  When no provider
calendar is available, the API reports `weekday_fallback` in its freshness
metadata so a consumer can distinguish the degraded mode.

Example provider configuration:

```yaml
datasets:
  calendar:
    url: https://api.example.com/trade_cal
    method: POST
    response_path: data
    start_body_path: params.start_date
    end_body_path: params.end_date
    date_only: true
    date_format: "%Y%m%d"
    field_map:
      cal_date: date
      is_open: is_open
```
