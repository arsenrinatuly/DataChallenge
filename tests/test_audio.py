import base64
import json
import os
import tempfile
import unittest

os.environ.setdefault("CQA_DB", os.path.join(tempfile.mkdtemp(), "t.sqlite3"))
import server  # noqa: E402


class AudioUnwrapTest(unittest.TestCase):
    def test_raw_mp3(self):
        data, ctype = server.unwrap_audio(b"ID3....", "application/octet-stream")
        self.assertEqual((data, ctype), (b"ID3....", "audio/mpeg"))

    def test_power_automate_json_wrapper(self):
        raw = b"RIFF\x00\x00\x00\x00WAVE"
        body = json.dumps({"$content-type": "application/octet-stream",
                           "$content": base64.b64encode(raw).decode()}).encode()
        self.assertEqual(server.unwrap_audio(body, "application/json"), (raw, "audio/wav"))

    def test_link_in_json(self):
        body = json.dumps({"body": {"url": "https://files.example/rec.mp3"}}).encode()
        self.assertEqual(server.unwrap_audio(body, "application/json"), (None, "https://files.example/rec.mp3"))

    def test_power_automate_html_player(self):
        page = (b'<!DOCTYPE html><html><body><audio id="a" controls>'
                b'<source src="https://x.dynamics.com/api/filedownload/1?sp=r&amp;sig=a%2Bb" type="audio/mpeg">'
                b'</audio></body></html>')
        self.assertEqual(server.unwrap_audio(page, "text/html; charset=utf-8"),
                         (None, "https://x.dynamics.com/api/filedownload/1?sp=r&sig=a%2Bb"))

    def test_json_without_audio(self):
        with self.assertRaises(server.ApiError):
            server.unwrap_audio(b'{"error": "nope"}', "application/json")


if __name__ == "__main__":
    unittest.main()
