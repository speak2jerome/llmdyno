import argparse
import json
import sys

from ._mode import USE_DECIMAL
from .errors import InventoryError
from .models import Item
from .store import InventoryStore


def fmt(v):
    return f"{v:.2f}"


def main(argv=None):
    p = argparse.ArgumentParser(prog="inventory")
    p.add_argument("--db", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("sku"); a.add_argument("name"); a.add_argument("qty", type=int); a.add_argument("price")
    sub.add_parser("remove").add_argument("sku")
    sub.add_parser("list")
    ad = sub.add_parser("adjust"); ad.add_argument("sku"); ad.add_argument("delta", type=int); ad.add_argument("--reason", required=True)
    sub.add_parser("history").add_argument("sku", nargs="?")
    sub.add_parser("search").add_argument("query")
    sub.add_parser("report").add_argument("--format", choices=["json", "csv"], required=True)
    sub.add_parser("undo").add_argument("sku", nargs="?")
    args = p.parse_args(argv)
    try:
        s = InventoryStore(args.db)
        line = lambda i: print(f"{i.sku}\t{i.name}\t{i.qty}\t{fmt(i.price)}")
        mline = lambda m: print(f"{m.timestamp}\t{m.sku}\t{m.delta}\t{m.reason}")
        if args.cmd == "add":
            s.add_item(Item(args.sku, args.name, args.qty, args.price if USE_DECIMAL else float(args.price)))
        elif args.cmd == "remove":
            s.remove_item(args.sku)
        elif args.cmd in ("list", "search"):
            for i in (s.list_items() if args.cmd == "list" else s.search(args.query)):
                line(i)
        elif args.cmd == "adjust":
            s.adjust(args.sku, args.delta, args.reason)
        elif args.cmd == "history":
            for m in s.history(args.sku):
                mline(m)
        elif args.cmd == "undo":
            mline(s.undo_last_adjustment(args.sku))
        elif args.cmd == "report":
            items = s.list_items()
            if args.format == "json":
                conv = (lambda v: fmt(v)) if USE_DECIMAL else (lambda v: round(float(v), 2))
                print(json.dumps({"items": [{"sku": i.sku, "name": i.name, "qty": i.qty, "price": conv(i.price),
                                             "value": conv(i.price * i.qty)} for i in items], "total_value": conv(s.total_value())}))
            else:
                print("sku,name,qty,price,value")
                for i in items:
                    print(f"{i.sku},{i.name},{i.qty},{fmt(i.price)},{fmt(i.price * i.qty)}")
    except InventoryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main())
