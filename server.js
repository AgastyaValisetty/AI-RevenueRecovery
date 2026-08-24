const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = 500;

const server = http.createServer((req, res) => {
  let filePath = path.join(__dirname, 'dummy-front-end', req.url === '/' ? 'index.html' : req.url);
  let extName = path.extname(filePath);
  
  let contentType = 'text/html';
  switch (extName) {
    case '.js': contentType = 'text/javascript'; break;
    case '.css': contentType = 'text/css'; break;
    case '.json': contentType = 'application/json'; break;
    case '.png': contentType = 'image/png'; break;
    case '.jpg': contentType = 'image/jpg'; break;
  }
  
  fs.readFile(filePath, (err, content) => {
    if (err) {
      if (err.code === 'ENOENT') {
        res.writeHead(404);
        res.end('File not found', 'utf-8');
      } else {
        res.writeHead(500);
        res.end('Server Error: ' + err.code, 'utf-8');
      }
    } else {
      res.writeHead(200, { 'Content-Type': contentType });
      res.end(content, 'utf-8');
    }
  });
});

server.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}/`);
});