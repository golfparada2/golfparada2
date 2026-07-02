@echo off
cd /d "%~dp0"
:: Hledej turnaje z poslednich 3 dni (chyti vicedenne turnaje)
python -c "
from datetime import date, timedelta
d2 = date.today() - timedelta(days=1)
d1 = d2 - timedelta(days=2)
import subprocess, sys
subprocess.run([sys.executable, 'daily_golf_update.py', d1.strftime('%%Y-%%m-%%d'), d2.strftime('%%Y-%%m-%%d')])
" >> daily_update.log 2>&1
