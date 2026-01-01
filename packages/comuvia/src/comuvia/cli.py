"""The ``comuvia`` command-line interface (standard library ``argparse``; no network command).

Exit codes: 0 success (exclusions are results, not errors); 1 refusal or mismatch; 2 usage error.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from . import __version__
from .evaluation import evaluate, evaluation_records, reproduce
from .identity import content_digest, record_digest, verify
from .issues import Issue, RefusalError
from .selectors import check_selector
from .store import RecordStore
from .validation import instant, load_record, validate

OK, FAILED, USAGE = 0, 1, 2


class _Output:
    def __init__(self, as_json: bool):
        self.as_json = as_json

    def emit(self, data: dict, lines: list[str]) -> None:
        if self.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            for line in lines:
                print(line)


def _issues(issues) -> list[dict]:
    return [{"code": i.code, "pointer": i.pointer, "message": i.message} for i in issues]


def _issue_lines(issues, indent: str = "  ") -> list[str]:
    return [f"{indent}{i.code} at '{i.pointer}': {i.message}" for i in issues]


def _read_record(path: str) -> dict:
    return load_record(Path(path).read_bytes())


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ commands


def cmd_validate(args, out: _Output) -> int:
    results, lines, failed = [], [], False
    for path in args.files:
        try:
            body = _read_record(path)
            results.append({"file": path, "valid": True, "record_digest": record_digest(body), "issues": []})
            lines.append(f"valid    {path}  {record_digest(body)}")
        except RefusalError as error:
            failed = True
            results.append({"file": path, "valid": False, "issues": _issues(error.issues)})
            lines += [f"REFUSED  {path}"] + _issue_lines(error.issues)
    out.emit({"results": results}, lines)
    return FAILED if failed else OK


def cmd_digest(args, out: _Output) -> int:
    data = Path(args.file).read_bytes()
    if args.content:
        digest, kind = content_digest(data), "content"
    else:
        digest, kind = record_digest(load_record(data)), "record"
    out.emit({"kind": kind, "digest": digest, "byte_length": len(data) if args.content else None}, [digest])
    return OK


def cmd_verify(args, out: _Output) -> int:
    body = _read_record(args.record)
    content = Path(args.content).read_bytes() if args.content else None
    records = RecordStore(args.store).records() if args.store else []
    result = verify(body, expected_digest=args.expected_digest, content=content, records=records)
    selector = None
    if body["record_type"] == "source_assertion" and content is not None:
        snapshot = next((r for r in records if r["record_type"] == body["resource"]["record_type"]
                         and r["id"] == body["resource"]["id"] and r["revision"] == body["resource"]["revision"]), None)
        selector = check_selector(body, content, snapshot=snapshot)
    issues = list(result.issues) + (list(selector.issues) if selector else [])
    data = {
        "record_digest": result.record_digest,
        "record_identity": result.record_identity,
        "content_identity": result.content_identity,
        "references": [{"pointer": r.pointer, "result": r.result} for r in result.references],
        "selector": None if selector is None else {"result": selector.result, "checked": list(selector.checked)},
        "timestamp_assurance": result.timestamp_assurance,
        "signature": result.signature,
        "issues": _issues(issues),
    }
    lines = [
        f"record digest       {result.record_digest}",
        f"record identity     {result.record_identity}",
        f"content identity    {result.content_identity}",
    ]
    lines += [f"reference {r.pointer:<10} {r.result}" for r in result.references]
    if selector is not None:
        lines.append(f"selector            {selector.result} ({', '.join(selector.checked) or 'nothing checkable'})")
    lines += [f"timestamp assurance {result.timestamp_assurance}", f"signature           {result.signature}"]
    lines += _issue_lines(issues)
    out.emit(data, lines)
    mismatch = issues or (selector is not None and selector.result == "mismatch")
    return FAILED if mismatch else OK


def cmd_store_init(args, out: _Output) -> int:
    RecordStore.create(args.store)
    out.emit({"store": args.store, "created": True}, [f"created store {args.store}"])
    return OK


def cmd_store_append(args, out: _Output) -> int:
    bodies = [_read_record(path) for path in args.files]
    entries = []
    with RecordStore(args.store, writer=True) as store:
        for path, body in zip(args.files, bodies):
            entry = store.append(body)
            entries.append({"file": path, **entry.as_index(), "appended": entry.appended})
    lines = [
        f"{'appended' if e['appended'] else 'present '} seq={e['sequence']} {e['record_type']} {e['id']} r{e['revision']} {e['digest']}"
        for e in entries
    ]
    out.emit({"entries": entries}, lines)
    return OK


def cmd_store_verify(args, out: _Output) -> int:
    report = RecordStore(args.store).verify()
    data = {
        "ok": report.ok,
        "entries": report.entries,
        "bodies": report.bodies,
        "lock_holder": report.lock_holder,
        "lock_note": "holder details last written by a writer; a reader cannot tell whether that holder is still alive",
        "scope": "identity and references only; run 'comuvia reproduce' to check stored evaluation results",
        "issues": _issues(report.issues),
        "detection_limit": report.detection_limit,
    }
    holder = report.lock_holder or "none recorded"
    lines = [f"{'OK' if report.ok else 'PROBLEMS FOUND'}: {report.entries} index entries, {report.bodies} bodies"]
    lines.append(f"writer details last recorded: {holder} (a reader cannot tell whether that writer is alive)")
    lines += _issue_lines(report.issues)
    lines.append(f"limit: {report.detection_limit}")
    lines.append("scope: identity and references only; run 'comuvia reproduce' to check stored evaluation results")
    out.emit(data, lines)
    return OK if report.ok else FAILED


def cmd_store_show(args, out: _Output) -> int:
    store = RecordStore(args.store)
    if args.latest:
        bodies = [b for _, b in sorted(store.latest().items())]
    else:
        bodies = store.records()
    if args.record_type:
        bodies = [b for b in bodies if b["record_type"] == args.record_type]
    if args.id:
        bodies = [b for b in bodies if b["id"] == args.id]
    rows = [{"record_type": b["record_type"], "id": b["id"], "revision": b["revision"], "digest": record_digest(b)} for b in bodies]
    data = {"records": bodies if args.bodies else rows}
    out.emit(data, [f"{r['record_type']:<20} {r['id']} r{r['revision']} {r['digest']}" for r in rows])
    return OK


def cmd_store_repair(args, out: _Output) -> int:
    with RecordStore(args.store, writer=True) as store:
        removed = store.truncate_torn_tail()
    out.emit({"torn_bytes_removed": removed}, [f"removed {removed} bytes of an incomplete final index line"])
    return OK


def cmd_evaluate(args, out: _Output) -> int:
    if args.append and not args.store:
        raise _Usage("--append requires --store")
    if args.append and (not args.evaluated_at or not args.recorded_by):
        raise _Usage("--append requires --evaluated-at and --recorded-by")
    for name in ("evaluated_at", "recorded_at"):
        value = getattr(args, name)
        if value is not None and instant(value) is None:
            raise _Usage(f"--{name.replace('_', '-')} must be an RFC 3339 timestamp with an offset")
    records = RecordStore(args.store).records() if args.store else [_read_record(p) for p in args.files]
    report = evaluate(records)
    data = report.as_json()
    appended = []
    if args.append:
        bodies = evaluation_records(
            report, records,
            evaluated_at=args.evaluated_at, recorded_by=args.recorded_by, recorded_at=args.recorded_at or _now(),
        )
        with RecordStore(args.store, writer=True) as store:
            for body in bodies:
                entry = store.append(body)
                appended.append({"id": body["id"], "digest": entry.digest, "appended": entry.appended})
        data["evaluation_records"] = appended
    counts = report.counts
    lines = [f"scoring rule {report.scoring_rule['id']} v{report.scoring_rule['version']} {report.scoring_rule['digest']}"]
    lines.append("counts: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for r in report.results:
        loss = "" if r.loss is None else f" loss {json.dumps(r.loss)}"
        why = f" ({', '.join(r.reasons)})" if r.reasons else ""
        lines.append(f"  {r.status:<10} {r.kind:<9} {r.record['id']} r{r.record['revision']}{loss}{why}")
    lines += [f"  {'appended' if a['appended'] else 'present'} evaluation {a['id']}" for a in appended]
    lines.append("no aggregate score is computed")
    out.emit(data, lines)
    return OK


def cmd_reproduce(args, out: _Output) -> int:
    store = RecordStore(args.store)
    records = store.records()
    evaluations = [b for b in records if b["record_type"] == "evaluation"]
    if args.ids:
        evaluations = [b for b in evaluations if b["id"] in set(args.ids)]
        missing = set(args.ids) - {b["id"] for b in evaluations}
        if missing:
            raise _Usage(f"no stored evaluation with id {sorted(missing)}")
    results, lines, failed = [], [], False
    for body in evaluations:
        reproduction = reproduce(body, records)
        failed |= reproduction.result != "match"
        results.append({
            "id": body["id"], "revision": body["revision"], "result": reproduction.result,
            "reason": reproduction.reason, "stored": reproduction.stored, "recomputed": reproduction.recomputed,
        })
        loss = reproduction.stored.get("loss")
        lines.append(f"{reproduction.result:<11} {body['id']} r{body['revision']} loss {json.dumps(loss)}"
                     + (f" ({reproduction.reason})" if reproduction.reason else ""))
    out.emit({"results": results}, lines or ["no stored evaluations"])
    return FAILED if failed else OK


# ------------------------------------------------------------------ parser


class _Usage(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    # --json is accepted before or after the command; SUPPRESS keeps a subcommand's default
    # from overwriting a value given at the top level.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON output")
    parser = argparse.ArgumentParser(
        prog="comuvia",
        description="Offline evidence and prediction records: validate, digest, verify, store, evaluate, reproduce.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    parser.add_argument("--version", action="version", version=f"comuvia {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", parents=[common], help="validate record files")
    p.add_argument("files", nargs="+")
    p.set_defaults(handler=cmd_validate)

    p = sub.add_parser("digest", parents=[common], help="record digest of a record file, or content digest of raw bytes")
    p.add_argument("file")
    p.add_argument("--content", action="store_true", help="digest the file's exact bytes instead of a record")
    p.set_defaults(handler=cmd_digest)

    p = sub.add_parser("verify", parents=[common], help="verify a record against content bytes and a store")
    p.add_argument("record")
    p.add_argument("--content", help="retained bytes of the record's resource (snapshot, descriptor or assertion)")
    p.add_argument("--expected-digest", help="the record digest the record should have")
    p.add_argument("--store", help="store whose records resolve the record's references")
    p.set_defaults(handler=cmd_verify)

    store = sub.add_parser("store", parents=[common], help="single-writer record store").add_subparsers(dest="store_command", required=True)
    p = store.add_parser("init", parents=[common], help="create an empty store")
    p.add_argument("store")
    p.set_defaults(handler=cmd_store_init)
    p = store.add_parser("append", parents=[common], help="append record files (takes the writer lock)")
    p.add_argument("store")
    p.add_argument("files", nargs="+")
    p.set_defaults(handler=cmd_store_append)
    p = store.add_parser(
        "verify", parents=[common],
        help="check index, bodies and references by name (identity only; use 'reproduce' for evaluation results)",
    )
    p.add_argument("store")
    p.set_defaults(handler=cmd_store_verify)
    p = store.add_parser("show", parents=[common], help="list stored records")
    p.add_argument("store")
    p.add_argument("--latest", action="store_true", help="latest revision per record only")
    p.add_argument("--record-type")
    p.add_argument("--id")
    p.add_argument("--bodies", action="store_true", help="include full record bodies (with --json)")
    p.set_defaults(handler=cmd_store_show)
    p = store.add_parser("repair", parents=[common], help="operator action: remove an incomplete final index line")
    p.add_argument("store")
    p.add_argument("--truncate-torn-tail", action="store_true", required=True)
    p.add_argument("--confirm", action="store_true", required=True)
    p.set_defaults(handler=cmd_store_repair)

    p = sub.add_parser("evaluate", parents=[common], help="evaluate forecasts and narrative candidates")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--store")
    source.add_argument("--files", nargs="+")
    p.add_argument("--append", action="store_true", help="append evaluation records to the store")
    p.add_argument("--evaluated-at", help="explicit evaluation time for appended records (RFC 3339)")
    p.add_argument("--recorded-by", help="agent recording the evaluations, e.g. evaluator:name")
    p.add_argument("--recorded-at", help="recording time (RFC 3339); defaults to now")
    p.set_defaults(handler=cmd_evaluate)

    p = sub.add_parser("reproduce", parents=[common], help="re-derive stored evaluations from their pinned inputs")
    p.add_argument("--store", required=True)
    p.add_argument("ids", nargs="*", help="evaluation ids (default: every stored evaluation)")
    p.set_defaults(handler=cmd_reproduce)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = _Output(args.json)
    try:
        return args.handler(args, out)
    except _Usage as error:
        parser.print_usage(sys.stderr)
        print(f"comuvia: error: {error}", file=sys.stderr)
        return USAGE
    except RefusalError as error:
        out.emit({"refused": True, "issues": _issues(error.issues)}, ["REFUSED"] + _issue_lines(error.issues))
        return FAILED
    except FileNotFoundError as error:
        out.emit({"refused": True, "issues": [{"code": "file_not_found", "pointer": "", "message": str(error)}]},
                 [f"REFUSED: {error}"])
        return FAILED


if __name__ == "__main__":
    sys.exit(main())
