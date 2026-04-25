const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');

const API_KEY = process.env.API_KEY || 'your_api_key_here_>:D';
const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://api:8000';
const FIRECRAWL_URL = process.env.FIRECRAWL_API_URL || 'http://firecrawl-api:3002/v1';

// Persistent agent for faster subsequent requests to the LLM API
const zaiAgent = new https.Agent({ keepAlive: true, maxSockets: 10 });

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
};

const TOOLS = [
  {
    type: 'function',
    function: {
      name: 'web_search',
      description: 'Search the web for real-time information about agricultural prices, weather, or regional events in Malaysia.',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'The search query' },
          location: { type: 'string', description: 'Specific location in Malaysia (optional)' }
        },
        required: ['query']
      }
    }
  }
];

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
    req.on('end', async () => {
      let parsed;
      try { parsed = JSON.parse(body); } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid JSON' }));
        return;
      }

      try {
        const result = await runChatCompletion(parsed.messages);
        const duration = Date.now() - start;
        console.log(`LLM Request completed in ${duration}ms`);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (err) {
        console.error('LLM Proxy Error:', err);
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: `LLM service unavailable: ${err.message}` }));
      }
    });
    return;
  }

  // ── Serve static files ──
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

async function runChatCompletion(messages) {
  const payload = {
    model: 'ilmu-glm-5.1',
    max_tokens: 800,
    temperature: 0.2,
    messages: messages,
    tools: TOOLS
  };

  let response = await callLLM(payload);
  const choice = response.choices?.[0];

  if (choice?.finish_reason === 'tool_calls' || choice?.message?.tool_calls) {
    const toolCalls = choice.message.tool_calls;
    const newMessages = [...messages, choice.message];

    for (const toolCall of toolCalls) {
      if (toolCall.function.name === 'web_search') {
        const args = JSON.parse(toolCall.function.arguments);
        console.log(`Executing web_search: ${args.query} in ${args.location || 'Malaysia'}`);
        const searchResults = await executeWebSearch(args.query, args.location);

        newMessages.push({
          role: 'tool',
          tool_call_id: toolCall.id,
          name: 'web_search',
          content: JSON.stringify(searchResults)
        });
      }
    }

    // Call LLM again with tool results
    response = await callLLM({
      ...payload,
      messages: newMessages,
      tool_choice: 'none' // Don't let it call tools again to avoid loops
    });
  }

  return response;
}

function callLLM(payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const options = {
      hostname: 'api.ilmu.ai',
      path: '/v1/chat/completions',
      method: 'POST',
      agent: zaiAgent,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Length': Buffer.byteLength(body)
      }
    };

    const req = https.request(options, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`Failed to parse LLM response: ${data.substring(0, 100)}`));
        }
      });
    });

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function executeWebSearch(query, location) {
  const fullQuery = location ? `${query} in ${location} Malaysia` : `${query} Malaysia`;
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ query: fullQuery, limit: 3 });
    const url = new URL(`${FIRECRAWL_URL.rstrip('/')}/search`);

    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    };

    const client = url.protocol === 'https:' ? https : http;
    const req = client.request(options, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve({ error: 'Failed to parse search results', raw: data.substring(0, 100) });
        }
      });
    });

    req.on('error', err => {
      console.error('Search Request Error:', err);
      resolve({ error: `Search service unavailable: ${err.message}` });
    });
    req.write(body);
    req.end();
  });
}

// Helper to strip trailing slash
String.prototype.rstrip = function(char) {
  if (this.endsWith(char)) return this.substring(0, this.length - 1);
  return this;
};

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
