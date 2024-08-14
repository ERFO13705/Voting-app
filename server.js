// server.js
const express = require('express');
const bodyParser = require('body-parser');
const cors = require('cors');
const app = express();
const port = process.env.PORT || 3000;

// Импортируйте логику приложения
const bricsMiniApp = require('./bricsMiniApp');

app.use(cors());
app.use(bodyParser.json());

// Роуты для работы с пользователями
app.post('/register', (req, res) => {
  const { id, name } = req.body;
  const user = bricsMiniApp.registerUser(id, name);
  res.json({ success: true, user });
});

app.post('/verify', (req, res) => {
  const { adminId, userId } = req.body;
  const admin = bricsMiniApp.getAdminById(adminId);
  const user = bricsMiniApp.getUserById(userId);
  if (admin && user) {
    admin.verifyUser(user);
    res.json({ success: true, message: 'User verified' });
  } else {
    res.status(400).json({ success: false, message: 'Invalid admin or user' });
  }
});

// Роуты для голосования
app.post('/start-voting', (req, res) => {
  const { adminId, title, options } = req.body;
  const session = bricsMiniApp.startVoting(adminId, title, options);
  if (session) {
    res.json({ success: true, session });
  } else {
    res.status(400).json({ success: false, message: 'Failed to start voting' });
  }
});

app.post('/vote', (req, res) => {
  const { userId, sessionIndex, optionIndex } = req.body;
  bricsMiniApp.vote(userId, sessionIndex, optionIndex);
  res.json({ success: true, message: 'Vote recorded' });
});

app.post('/close-voting', (req, res) => {
  const { adminId, sessionIndex } = req.body;
  bricsMiniApp.closeVoting(adminId, sessionIndex);
  res.json({ success: true, message: 'Voting session closed' });
});

// Роут для получения истории игр пользователя
app.get('/user-history/:userId', (req, res) => {
  const { userId } = req.params;
  const history = bricsMiniApp.getUserGameHistory(userId);
  res.json({ success: true, history });
});

app.listen(port, () => {
  console.log(`Server running on port ${port}`);
});