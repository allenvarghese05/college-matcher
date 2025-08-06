#!/bin/bash

echo "🎓 College Matcher MVP - Installation Script"
echo "============================================="

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js first."
    echo "Visit: https://nodejs.org/"
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm first."
    exit 1
fi

echo "✅ Node.js and npm are installed"

# Install backend dependencies
echo "📦 Installing backend dependencies..."
npm install

# Install frontend dependencies
echo "📦 Installing frontend dependencies..."
cd client
npm install
cd ..

echo "✅ All dependencies installed successfully!"

# Create uploads directory
echo "📁 Creating uploads directory..."
mkdir -p server/uploads

echo ""
echo "🎉 Installation complete!"
echo ""
echo "To start the application:"
echo "1. Run: npm run dev"
echo "2. Open: http://localhost:3000"
echo ""
echo "The backend will run on port 5000 and frontend on port 3000"
echo ""
echo "Happy coding! 🚀" 