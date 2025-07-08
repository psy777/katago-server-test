const express = require('express');
const { analyze } = require('./engine');

const app = express();
app.use(express.json());

app.post('/analyze', async (req, res) => {
  console.log('--- /analyze hit ---', req.body);
  try {
    const info = await analyze(req.body.moves || [], req.body.visits || 100);
    res.json(info);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.toString() });
  }
});

const PORT = 8080;
app.listen(PORT, () => {
  console.log(`KataGo API listening on http://localhost:${PORT}`);
});
