"""Seven-day reviews from recorded own-business results, never listing signals."""
from datetime import timedelta
from decimal import Decimal

from src.domain.models.opportunity import CostAssumptions
from src.domain.models.opportunity_business import business_today
from src.domain.opportunity_scoring import profit_analysis


def realized_profit(entry):
    costs = CostAssumptions(expected_sale_price=entry.revenue, purchase_cost=entry.purchase_cost,
        shipping_cost=entry.shipping_cost, platform_fee=entry.platform_fee,
        fulfillment_cost=entry.fulfillment_cost, expected_loss=entry.actual_loss)
    result = profit_analysis(costs, refund_amount=entry.refund_amount)
    result["basis"] = "自营人工经营记录；销售收入减退款及全部实际费用，未独立核实"
    return result


def experiment_review(start_date, status, entries, stop_reason):
    days = {entry.day for entry in entries}
    expected = {start_date+timedelta(days=i) for i in range(7)}
    missing_days = sorted(expected-days)
    profits = [realized_profit(entry) for entry in entries]
    all_finances = bool(entries) and all(p["net_profit"] is not None for p in profits)
    recorded_net = str(sum((Decimal(str(p["net_profit"])) for p in profits), Decimal(0))) if all_finances else None
    metrics = {key: sum(getattr(e,key) for e in entries) if entries and all(getattr(e,key) is not None for e in entries) else None
               for key in ("exposure","inquiries","orders","refunds")}
    elapsed = (business_today()-start_date).days >= 6
    missing = [f"{entry.day}: {','.join(profit['missing'])}" for entry, profit in zip(entries,profits) if profit["missing"]]
    complete = not missing_days and all_finances and metrics["orders"] is not None and metrics["refunds"] is not None
    net = Decimal(recorded_net) if recorded_net is not None else None
    if status == "stopped":
        decision, reasons = "stop", [stop_reason]
    elif missing or elapsed and not complete:
        decision, reasons = "fill_evidence", ["缺少经营日记录、实际费用或订单/退款数；不可推断完整七天结果"]
    elif complete and (net <= 0 or metrics["orders"] == 0 or metrics["refunds"] > 0 or any(e.refund_amount > 0 for e in entries)):
        decision, reasons = "stop", ["七天净收益不为正、无订单或出现退款，建议暂停复核成本与交付（保守启发式）"]
    elif complete:
        decision, reasons = "continue", ["完整七天记录显示正净收益、有订单且无退款，可继续人工验证"]
    else:
        decision, reasons = "test", ["七天窗口进行中，继续记录自营结果"]
    return {"decision":decision, "reasons":reasons, "recorded_days":len(entries),
            "missing_days":[d.isoformat() for d in missing_days], "missing_finances":missing,
            "recorded_net":recorded_net, "seven_day_net":recorded_net if complete else None,
            "metrics":metrics, "complete":complete, "window_ended":elapsed,
            "note":"仅使用人工自营记录。未记录不是零；退款可发生在订单之后；建议未经业务校准，不执行采购/发布。"}
