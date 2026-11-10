import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
import summary_generation as generation

DRAFT = ' '.join(['word'] * 60)

class GenerationTests(unittest.TestCase):
    def test_word_count_retry(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch.object(generation,'extract_issue_text',return_value='source'), patch.object(generation,'request_draft',side_effect=['too short',DRAFT]) as provider:
            self.assertEqual(generation.generate_summary('unused','Issue'),DRAFT)
            self.assertEqual(provider.call_count,2)

    def test_missing_key_does_not_call_provider(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':''}), patch.object(generation,'request_draft') as provider:
            with self.assertRaises(generation.SummaryUnavailable): generation.generate_summary('unused','Issue')
            provider.assert_not_called()

    def test_endpoint_preserves_existing_and_failed_upload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'active_storage_path',Path(directory)):
            manifest={'slug':'new-test','title':'Issue','flipbook_type':'magazine','original_pdf_path':'saved.pdf','summary_generation_eligible':True}
            main.write_manifest('new-test',manifest)
            client=TestClient(main.app,base_url='https://testserver')
            url='/admin/api/publications/new-test/generate-summary'
            self.assertIn(client.post(url).status_code,[401,403])
            client.post('/admin/login',data={'password':'1313'})
            with patch.object(main,'generate_summary',side_effect=generation.SummaryUnavailable('Unavailable')):
                self.assertEqual(client.post(url).status_code,503)
            self.assertEqual(main.read_manifest('new-test'),manifest)
            with patch.object(main,'generate_summary',return_value=DRAFT) as provider:
                self.assertEqual(client.post(url).status_code,200)
                self.assertEqual(client.post(url).json()['status'],'existing')
                self.assertEqual(provider.call_count,1)
            self.assertFalse(main.read_manifest('new-test')['summary_generation_eligible'])

    def test_existing_issue_not_eligible(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main,'active_storage_path',Path(directory)):
            main.write_manifest('old-test',{'slug':'old-test','flipbook_type':'magazine'})
            client=TestClient(main.app,base_url='https://testserver')
            client.post('/admin/login',data={'password':'1313'})
            with patch.object(main,'generate_summary') as provider:
                self.assertEqual(client.post('/admin/api/publications/old-test/generate-summary').status_code,409)
                provider.assert_not_called()
