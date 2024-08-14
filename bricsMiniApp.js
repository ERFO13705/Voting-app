// Основная структура приложения
const app = {
    users: [],
    admins: [],
    votingSessions: [],
    gameHistory: []
  };
  
  // Класс пользователя
  class User {
    constructor(id, name) {
      this.id = id;
      this.name = name;
      this.isVerified = false;
      this.gameHistory = [];
    }
  
    verify() {
      this.isVerified = true;
    }
  
    addGameToHistory(game) {
      this.gameHistory.push(game);
    }
  }
  
  // Класс администратора
  class Admin {
    constructor(id, name) {
      this.id = id;
      this.name = name;
    }
  
    verifyUser(user) {
      user.verify();
    }
  
    createVotingSession(title, options) {
      const newSession = new VotingSession(title, options);
      app.votingSessions.push(newSession);
      return newSession;
    }
  }
  
  // Класс сессии голосования
  class VotingSession {
    constructor(title, options) {
      this.title = title;
      this.options = options;
      this.votes = {};
      this.isActive = true;
    }
  
    vote(userId, optionIndex) {
      if (this.isActive && optionIndex < this.options.length) {
        this.votes[userId] = optionIndex;
      }
    }
  
    getResults() {
      const results = this.options.map(option => ({ option, count: 0 }));
      Object.values(this.votes).forEach(optionIndex => {
        results[optionIndex].count++;
      });
      return results;
    }
  
    close() {
      this.isActive = false;
      app.gameHistory.push({
        title: this.title,
        results: this.getResults(),
        date: new Date()
      });
    }
  }
  
  // Функции для работы с пользователями
  function registerUser(id, name) {
    const newUser = new User(id, name);
    app.users.push(newUser);
    return newUser;
  }
  
  function getUserById(id) {
    return app.users.find(user => user.id === id);
  }
  
  // Функции для работы с администраторами
  function registerAdmin(id, name) {
    const newAdmin = new Admin(id, name);
    app.admins.push(newAdmin);
    return newAdmin;
  }
  
  function getAdminById(id) {
    return app.admins.find(admin => admin.id === id);
  }
  
  // Функции для голосования
  function startVoting(adminId, title, options) {
    const admin = getAdminById(adminId);
    if (admin) {
      return admin.createVotingSession(title, options);
    }
    return null;
  }
  
  function vote(userId, sessionIndex, optionIndex) {
    const user = getUserById(userId);
    if (user && user.isVerified && app.votingSessions[sessionIndex]) {
      app.votingSessions[sessionIndex].vote(userId, optionIndex);
    }
  }
  
  function closeVoting(adminId, sessionIndex) {
    const admin = getAdminById(adminId);
    if (admin && app.votingSessions[sessionIndex]) {
      app.votingSessions[sessionIndex].close();
    }
  }
  
  // Функция для получения истории игр пользователя
  function getUserGameHistory(userId) {
    const user = getUserById(userId);
    return user ? user.gameHistory : [];
  }
  
  // Пример использования
  function exampleUsage() {
    // Регистрация пользователей и админов
    const user1 = registerUser(1, "Alice");
    const user2 = registerUser(2, "Bob");
    const admin = registerAdmin(101, "Admin");
  
    // Верификация пользователей
    admin.verifyUser(user1);
    admin.verifyUser(user2);
  
    // Создание сессии голосования
    const votingSession = startVoting(101, "BRICS Policy Vote", ["Option A", "Option B", "Option C"]);
  
    // Голосование
    vote(1, 0, 1); // Alice голосует за Option B
    vote(2, 0, 2); // Bob голосует за Option C
  
    // Закрытие голосования
    closeVoting(101, 0);
  
    // Получение истории игр
    console.log(getUserGameHistory(1));
  }
  
  // Запуск примера использования
  exampleUsage();