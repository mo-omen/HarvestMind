const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const API_KEY = process.env.API_KEY || 'your_api_key_here_>:D';
const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://api:8000';

// Persistent agent for faster subsequent requests to the LLM API
const zaiAgent = new https.Agent({ keepAlive: true, maxSockets: 10 });

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
};

const server = http.createServer((req, res) => {
  const start = Date.now();
  console.log(`${new Date().toISOString()} ${req.method} ${req.url}`);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.url.startsWith('/api/v1/')) {
    proxyToBackend(req, res);
    return;
  }

  // ── API proxy route ──
  if (req.method === 'POST' && req.url === '/api/chat') {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      let parsed;
      try { parsed = JSON.parse(body); } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON' }));
        return;
      }

      const payload = JSON.stringify({
        model: 'ilmu-glm-5.1',
        max_tokens: 550,
        temperature: 0.2,
        messages: parsed.messages
      });

      const options = {
        hostname: 'api.ilmu.ai',
        path: '/v1/chat/completions',
        method: 'POST',
        agent: zaiAgent,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Length': Buffer.byteLength(payload)
        }
      };

      const apiReq = https.request(options, (apiRes) => {
        let data = '';
        apiRes.on('data', chunk => data += chunk);
        apiRes.on('end', () => {
          const duration = Date.now() - start;
          console.log(`LLM Response received in ${duration}ms`);
          res.writeHead(apiRes.statusCode, { 'Content-Type': 'application/json' });
          res.end(data);
        });
      });

      apiReq.on('error', (err) => {
        console.error('LLM Proxy Error:', err);
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: `LLM service unavailable: ${err.message}` }));
      });

      apiReq.write(payload);
      apiReq.end();
    });
    return;
  }

  // ── Serve static files from root (__dirname) ──
  const requestPath = req.url.split('?')[0];
  let filePath = requestPath === '/' ? '/index.html' : requestPath;
  filePath = path.resolve(__dirname, `.${path.normalize(filePath)}`);
  if (!filePath.startsWith(__dirname)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'text/plain' });
    res.end(content);
  });
});

function proxyToBackend(req, res) {
  const target = new URL(req.url, BACKEND_URL);
  const client = target.protocol === 'https:' ? https : http;
  const options = {
    hostname: target.hostname,
    port: target.port || (target.protocol === 'https:' ? 443 : 80),
    path: `${target.pathname}${target.search}`,
    method: req.method,
    headers: {
      ...req.headers,
      host: target.host,
    },
  };

  const proxyReq = client.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: `Backend unavailable: ${err.message}` }));
  });

  req.pipe(proxyReq);
}

server.listen(PORT, () => {
  console.log(`\n🌾 HarvestMind running at http://localhost:${PORT}\n`);
});
