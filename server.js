const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const dns = require('dns');

// Fix for Node.js 20+ IPv6 networking issues in some Docker environments
// This prevents the AggregateError [ETIMEDOUT] and ENETUNREACH when connecting to external APIs
dns.setDefaultResultOrder('ipv4first');

const API_KEY = process.env.API_KEY || process.env.ILMU_API_KEY || '';

// Fail fast if API_KEY is missing or default
if (!API_KEY) {
  console.error("CRITICAL: API_KEY environment variable is missing. The application cannot function without an ILMU API key.");
  process.exit(1);
}

const PORT = process.env.PORT || 3000;
const BACKEND_URL = process.env.BACKEND_URL || 'http://api:8000';
const FIRECRAWL_URL = process.env.FIRECRAWL_API_URL || 'http://firecrawl-api:3002/v1';
const ILMU_BASE_URL = process.env.ILMU_BASE_URL || 'https://api.ilmu.ai/v1';
const ILMU_MODEL = process.env.ILMU_MODEL || 'ilmu-glm-5.1';
const LLM_TIMEOUT_MS = Number(process.env.LLM_TIMEOUT_MS || 30000);
const SEARCH_TIMEOUT_MS = Number(process.env.SEARCH_TIMEOUT_MS || 8000);
const LLM_MAX_RETRIES = Number(process.env.LLM_MAX_RETRIES || 1);
const MAX_TOOL_DEPTH = Number(process.env.MAX_TOOL_DEPTH || 1);
const WEB_SEARCH_ENABLED = process.env.ENABLE_WEB_SEARCH !== 'false';

// Persistent agent for faster subsequent requests to the LLM API
const zaiAgent = new https.Agent({ keepAlive: true, maxSockets: 10, family: 4 });

// Verify ILMU API connection on startup
function verifyApiConnection() {
  return new Promise((resolve) => {
    const targetUrl = new URL(ILMU_BASE_URL);
    const client = targetUrl.protocol === 'https:' ? https : http;
    const req = client.request(targetUrl, { method: 'HEAD', timeout: 5000, family: 4 }, (res) => {
      resolve(true);
    });
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
    req.on('error', () => resolve(false));
    req.end();
  });
}

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
  filePath = path.resolve(__dirname, 'public', `.${path.normalize(filePath)}`);
  if (!filePath.startsWith(path.join(__dirname, 'public'))) {
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

async function runChatCompletion(messages, depth = 0) {
  if (!Array.isArray(messages) || !messages.length) {
    const err = new Error('Request must include at least one chat message.');
    err.statusCode = 400;
    throw err;
  }

  const allowTools = WEB_SEARCH_ENABLED && depth < MAX_TOOL_DEPTH && shouldUseWebSearch(messages);
  const payload = {
    model: ILMU_MODEL,
    max_tokens: 800,
    temperature: 0.2,
    messages: messages
  };

  if (allowTools) {
    payload.tools = TOOLS;
  } else {
    payload.tool_choice = 'none';
  }

  let response = await callLLMWithRetry(payload);
  let choice = response.choices?.[0];

  if (choice?.finish_reason === 'tool_calls' || choice?.message?.tool_calls) {
    if (depth >= MAX_TOOL_DEPTH) {
      return response;
    }

    const toolCalls = choice.message.tool_calls;
    const newMessages = [...messages, choice.message];

    for (const toolCall of toolCalls) {
      if (toolCall.function.name === 'web_search') {
        let args = {};
        try {
          args = JSON.parse(toolCall.function.arguments || '{}');
        } catch (err) {
          console.warn('Invalid web_search arguments:', err.message);
        }
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

    // Recursively call LLM with tool results, incrementing depth
    response = await runChatCompletion(newMessages, depth + 1);
  }

  // Clean up any raw XML tool calls the model might have leaked in its text response
  choice = response.choices?.[0];
  if (choice?.message?.content) {
    choice.message.content = choice.message.content.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, '').trim();
    if (!choice.message.content) {
      choice.message.content = "I've reviewed the information, but I'm unable to provide a direct answer right now.";
    }
  }

  return response;
}

function shouldUseWebSearch(messages) {
  const lastUserMessage = [...messages].reverse().find(message => message.role === 'user');
  const content = String(lastUserMessage?.content || '').toLowerCase();
  return /\b(today|current|latest|recent|now|live|weather|rain|flood|drought|price|market|news|trend|forecast)\b/.test(content);
}

async function callLLMWithRetry(payload) {
  let lastError;

  for (let attempt = 0; attempt <= LLM_MAX_RETRIES; attempt += 1) {
    try {
      return await callLLM(payload, LLM_TIMEOUT_MS);
    } catch (err) {
      lastError = err;
      const retryable = isRetryableLLMError(err) && err.code !== 'REQUEST_TIMEOUT';
      if (!retryable || attempt >= LLM_MAX_RETRIES) break;
      await delay(400 * (attempt + 1));
    }
  }

  throw lastError;
}

function isRetryableLLMError(err) {
  if ([408, 429, 500, 502, 503, 504].includes(err.statusCode)) return true;
  return ['ECONNRESET', 'EAI_AGAIN', 'ETIMEDOUT', 'ENOTFOUND'].includes(err.code);
}

function callLLM(payload, timeoutMs) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const targetUrl = new URL(`${stripTrailingSlash(ILMU_BASE_URL)}/chat/completions`);
    const options = {
      hostname: targetUrl.hostname,
      port: targetUrl.port || (targetUrl.protocol === 'https:' ? 443 : 80),
      path: targetUrl.pathname + targetUrl.search,
      method: 'POST',
      agent: targetUrl.protocol === 'https:' ? zaiAgent : undefined,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Length': Buffer.byteLength(body)
      }
    };

    const client = targetUrl.protocol === 'https:' ? https : http;
    const req = client.request(options, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        let parsed;
        try {
          parsed = JSON.parse(data);
        } catch (e) {
          reject(new Error(`Failed to parse LLM response: ${data.substring(0, 100)}`));
          return;
        }

        if (res.statusCode < 200 || res.statusCode >= 300) {
          const message = parsed.error?.message || parsed.error || parsed.message || `LLM returned HTTP ${res.statusCode}`;
          const err = new Error(message);
          err.statusCode = res.statusCode;
          reject(err);
          return;
        }

        resolve(parsed);
      });
    });

    req.on('error', reject);
    req.setTimeout(timeoutMs, () => {
      const err = new Error(`LLM request timed out after ${Math.round(timeoutMs / 1000)}s`);
      err.code = 'REQUEST_TIMEOUT';
      req.destroy(err);
    });
    req.write(body);
    req.end();
  });
}

async function executeWebSearch(query, location) {
  if (!query) {
    return { error: 'Search query was empty.' };
  }

  const fullQuery = location ? `${query} in ${location} Malaysia` : `${query} Malaysia`;
  return new Promise((resolve) => {
    const body = JSON.stringify({ query: fullQuery, limit: 3 });
    const url = new URL(`${stripTrailingSlash(FIRECRAWL_URL)}/search`);

    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
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
        if (res.statusCode < 200 || res.statusCode >= 300) {
          resolve({ error: `Search service returned HTTP ${res.statusCode}` });
          return;
        }

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
    req.setTimeout(SEARCH_TIMEOUT_MS, () => {
      const err = new Error(`Search request timed out after ${Math.round(SEARCH_TIMEOUT_MS / 1000)}s`);
      req.destroy(err);
    });
    req.write(body);
    req.end();
  });
}

function stripTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

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

verifyApiConnection()
  .then((isReachable) => {
    if (!isReachable) {
      console.warn("WARNING: ILMU API could not be reached during startup check, but an API_KEY is present. Starting application anyway.");
    }
    server.listen(PORT, () => {
      console.log(`\n🌾 HarvestMind running at http://localhost:${PORT}\n`);
    });
  });
