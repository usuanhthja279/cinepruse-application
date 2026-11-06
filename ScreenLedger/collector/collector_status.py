#!/usr/bin/env python3
"""Export auditable, non-sales-proxy collector status from snapshots SQLite."""
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from smart_collector import open_db, last_hour_proxy, parse_local

IST=ZoneInfo('Asia/Kolkata')

def status_report(conn, movie_id: str, city: str, target_date: date, now: datetime) -> dict:
    captures=[dict(row) for row in conn.execute('''
       SELECT id,city,movie_id,observed_at_utc,reason,status,show_count,error
       FROM captures WHERE movie_id=? AND city=? ORDER BY observed_at_utc DESC LIMIT 50
    ''',(str(movie_id),city))]
    observations=conn.execute('''
       SELECT o.*,c.observed_at_utc FROM observations o
       JOIN captures c ON c.id=o.capture_id
       WHERE o.movie_id=? AND o.city=? ORDER BY c.observed_at_utc DESC
    ''',(str(movie_id),city)).fetchall()
    latest={}
    for row in observations:
        if row['session_key'] not in latest and parse_local(row['show_datetime_ist']).date()==target_date:
            latest[row['session_key']]=dict(row)
    complete_pricing=all(row['pricing_complete'] and row['estimated_gross_inr'] is not None for row in latest.values())
    job_status={}
    for row in conn.execute('SELECT status,count(*) n FROM final_jobs WHERE movie_id=? AND city=? GROUP BY status',
                            (str(movie_id),city)):
        job_status[row['status']]=row['n']
    started=sum(parse_local(row['show_datetime_ist'])<=now.astimezone(IST) for row in latest.values())
    total_seats=sum(row['total_seats'] or 0 for row in latest.values())
    valid_seats=[r for r in latest.values() if r['total_seats'] is not None and r['unavailable_seats'] is not None]
    unavailable=sum(r['unavailable_seats'] for r in valid_seats)
    result={
        'generated_at_ist':now.astimezone(IST).isoformat(timespec='seconds'),
        'movie_id':movie_id,'source_city':city,'target_date_ist':target_date.isoformat(),
        'source':'District HTML snapshots (only if provider access explicitly authorized)',
        'status':'sampled' if captures else 'not_collected',
        'snapshot_count':conn.execute('SELECT count(*) AS n FROM captures WHERE movie_id=? AND city=? AND status="ok"',(str(movie_id),city)).fetchone()['n'],
        'show_registry_count':len(latest),
        'started_shows_in_registry':started,
        'seat_capacity_known':total_seats,
        'unavailable_seats_proxy':unavailable if len(valid_seats)==len(latest) and latest else None,
        'unavailable_seat_occupancy_pct':round(100*unavailable/total_seats,2) if total_seats and len(valid_seats)==len(latest) else None,
        'assumed_gross_proxy_inr':round(sum(row['estimated_gross_inr'] for row in latest.values()),2) if latest and complete_pricing else None,
        'final_scan_job_statuses':job_status,
        'last_hour':last_hour_proxy(conn,movie_id,city,now),
        'recent_captures':captures[:12],
        'quality_flags':['unavailable_seats_include_booked_held_blocked',
                         'estimated_gross_is_not_verified_collection',
                         'never_sum_consecutive_snapshots',
                         'missing_city_or_show_is_not_zero',
                         'last_hour_requires_comparable_snapshots',
                         'future_and_started_show_coverage_may_be_incomplete'],
    }
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=Path('collector_data/smart_collector.sqlite'))
    p.add_argument('--date',required=True)
    p.add_argument('--movie-id',default='176276')
    p.add_argument('--city',default='kolkata')
    p.add_argument('--at',help='Local IST timestamp; defaults to now')
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    now=parse_local(args.at) if args.at else datetime.now(IST)
    conn=open_db(args.db)
    try:
        report=status_report(conn,str(args.movie_id),args.city,date.fromisoformat(args.date),now)
    finally:
        conn.close()
    payload=json.dumps(report,indent=2,ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(payload+'\n',encoding='utf-8')
        print(f'Exported {args.out}')
    else:print(payload)

if __name__=='__main__':main()
