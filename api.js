import { MockApi } from './mock.js';

export class Api {
  constructor(base = '/api') {
    this.base = base.replace(/\/$/, '');
    this.mock = new MockApi();
    this.mode = 'checking';
  }
  async init() {
    const params = new URLSearchParams(location.search);
    if (params.get('demo') === '1') { this.mode = 'demo'; return; }
    try { await this.live('GET', '/health'); this.mode = 'live'; }
    catch { this.mode = 'demo'; }
  }
  async live(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    const response = await fetch(`${this.base}${path}`, options);
    let data;
    try { data = await response.json(); } catch { data = {}; }
    if (!response.ok) {
      const error = new Error(data.error || `Ошибка сервера (${response.status})`);
      error.errors = data.errors;
      throw error;
    }
    return data;
  }
  request(method, path, body) {
    return this.mode === 'live' ? this.live(method, path, body) : this.mock.request(method, `/api${path}`, body);
  }
}
