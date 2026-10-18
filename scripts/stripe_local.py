"""Stripe CLI forwarding for local TEST subscriptions. No keys are printed."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
import httpx
from app.core.config import settings, BACKEND_DIR
from scripts.saas_setup import update_env

CLI=BACKEND_DIR/'.tools'/'stripe.exe'
EVENTS='checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,customer.subscription.paused,customer.subscription.resumed,invoice.paid,invoice.payment_failed,payment_intent.succeeded,payment_intent.canceled,payment_intent.payment_failed'


def install():
    if CLI.exists(): return
    if os.name!='nt': raise RuntimeError('Instala Stripe CLI desde docs.stripe.com/stripe-cli')
    with httpx.Client(follow_redirects=True,timeout=60) as client:
        result=client.get('https://api.github.com/repos/stripe/stripe-cli/releases/latest');result.raise_for_status()
        assets=result.json()['assets']
        asset=next(a for a in assets if a['name'].endswith('windows_x86_64.zip'))
        checksum=next(a for a in assets if a['name']=='stripe-windows-checksums.txt')
        manifest=client.get(checksum['browser_download_url']);manifest.raise_for_status()
        expected=next(line.split()[0] for line in manifest.text.splitlines() if line.split()[-1].lstrip('*')==asset['name'])
        binary=client.get(asset['browser_download_url']);binary.raise_for_status()
        if hashlib.sha256(binary.content).hexdigest()!=expected: raise RuntimeError('Checksum de Stripe CLI incorrecto')
        with zipfile.ZipFile(io.BytesIO(binary.content)) as archive:
            executable=next(name for name in archive.namelist() if Path(name).name=='stripe.exe')
            CLI.parent.mkdir(exist_ok=True);CLI.write_bytes(archive.read(executable))
    print('Stripe CLI oficial instalado dentro del proyecto, con checksum verificado.')


def cli_env():
    if not settings.STRIPE_SECRET_KEY.startswith(('sk_test_','rk_test_')):
        raise RuntimeError('El reenvío local requiere una clave Stripe de prueba')
    return dict(os.environ,STRIPE_API_KEY=settings.STRIPE_SECRET_KEY,STRIPE_DEVICE_NAME='DrapeMind-local')


def configure():
    install()
    result=subprocess.run([str(CLI),'listen','--print-secret'],env=cli_env(),capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    match=re.search(r'whsec_[A-Za-z0-9]+',result.stdout+result.stderr)
    if result.returncode or not match: raise RuntimeError('No se pudo configurar el webhook local')
    update_env('STRIPE_SAAS_WEBHOOK_SECRET',match.group())
    update_env('STRIPE_LOCAL_WEBHOOK_SECRET',match.group())
    print('Firma del webhook local guardada en .env. Reinicia el backend y ejecuta el reenvío Stripe.')


def listen(port):
    if not CLI.exists(): raise RuntimeError('Configura primero Stripe local')
    process=subprocess.Popen([str(CLI),'listen','--events',EVENTS,'--forward-to',f'http://127.0.0.1:{port}/api/v1/payments/stripe-local-webhook'],env=cli_env(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        for line in process.stdout:
            line=re.sub(r'(?:whsec|sk_test|rk_test)_[A-Za-z0-9]+','[credencial oculta]',line)
            print(line.rstrip(),flush=True)
        return process.wait()
    finally:
        if process.poll() is None: process.terminate()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['configure','listen']);parser.add_argument('--port',type=int,default=8000);args=parser.parse_args()
    try:
        if args.action=='configure':configure()
        else:raise SystemExit(listen(args.port))
    except Exception as exc:
        print('Stripe local no pudo iniciarse ('+type(exc).__name__+'). Revisa conexión y clave de prueba.');raise SystemExit(1)

if __name__=='__main__':main()
