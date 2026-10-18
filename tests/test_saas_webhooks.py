import hashlib
import hmac
import json
import time
from test_saas_isolation import client, factory
from app.core.config import settings


def signature(body,secret):
    stamp=str(int(time.time()))
    digest=hmac.new(secret.encode(),stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    return f't={stamp},v1={digest}'


def test_local_and_published_webhooks_require_their_own_signature(client,monkeypatch):
    monkeypatch.setattr(settings,'STRIPE_LOCAL_WEBHOOK_SECRET','whsec_test_local')
    monkeypatch.setattr(settings,'STRIPE_WEBHOOK_SECRET','whsec_test_published')
    raw=json.dumps({'id':'evt_unknown_payment','type':'payment_intent.succeeded','data':{'object':{'id':'pi_unknown'}}}).encode()
    local='/api/v1/payments/stripe-local-webhook';published='/api/v1/payments/stripe-webhook'
    assert client.post(local,content=raw).status_code==400
    assert client.post(local,content=raw,headers={'stripe-signature':signature(raw,'whsec_test_published')}).status_code==400
    assert client.post(local,content=raw,headers={'stripe-signature':signature(raw,'whsec_test_local')}).status_code==200
    assert client.post(published,content=raw,headers={'stripe-signature':signature(raw,'whsec_test_local')}).status_code==400
    assert client.post(published,content=raw,headers={'stripe-signature':signature(raw,'whsec_test_published')}).status_code==200
    monkeypatch.setattr(settings,'ENVIRONMENT','production')
    assert client.post(local,content=raw,headers={'stripe-signature':signature(raw,'whsec_test_local')}).status_code==404
