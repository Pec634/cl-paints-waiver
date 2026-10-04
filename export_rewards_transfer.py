"""Run locally to prepare the ignored private file for the live Rewards import."""
import json
from pathlib import Path
import app as main
from rewards_transfer import export_referrals

if __name__ == '__main__':
    with main.app.app_context():
        payload = export_referrals(main.db.engine)
        target = Path(main.app.instance_path) / 'rewards-transfer.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        print(f'Exported {len(payload["referrals"])} referrals and {len(payload["used_codes"])} used codes to {target}')
