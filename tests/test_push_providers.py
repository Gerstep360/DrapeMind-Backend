from unittest.mock import AsyncMock
import httpx
import pytest
from app.services import push_notifications as push


@pytest.mark.asyncio
@pytest.mark.parametrize('body,invalid', [({'error':{'status':'NOT_FOUND'}},False),
    ({'error':{'details':[{'errorCode':'UNREGISTERED'}]}},True)])
async def test_fcm_only_unregisters_expired_tokens_not_project_configuration_errors(monkeypatch,body,invalid):
    real_client=httpx.AsyncClient
    requests=[]
    def handle(request):
        requests.append(request);return httpx.Response(404,json=body)
    monkeypatch.setattr(push,'_get_google_oauth2_token',AsyncMock(return_value=('test-token','test-project')))
    monkeypatch.setattr(push.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handle)))
    result=await push.send_fcm_message(['provider-token','provider-token'],'Aviso','Mensaje',{})
    assert len(requests)==1
    assert result['sent']==0 and result['failed']==1
    assert bool(result['invalid_tokens']) is invalid


@pytest.mark.asyncio
async def test_missing_fcm_credentials_reports_failure_without_simulating_success(monkeypatch):
    monkeypatch.setattr(push,'_get_google_oauth2_token',AsyncMock(return_value=(None,'project')))
    result=await push.send_fcm_message(['provider-token'],'Aviso','Mensaje',{})
    assert result['sent']==0 and result['failed']==1 and result['configured'] is False


def test_browser_signing_key_is_stable_and_not_exposed(monkeypatch,tmp_path):
    from app.services.browser_push import public_key
    monkeypatch.setenv('WEB_PUSH_PRIVATE_KEY_PATH',str(tmp_path/'private.pem'))
    key=public_key()
    assert key==public_key() and len(key)==87
    assert 'PRIVATE KEY' not in key
