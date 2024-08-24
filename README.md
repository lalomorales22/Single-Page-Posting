# Rad Message Board

Rad Message Board is a single-user, Flask-based web application that allows you to create and manage your personal message board. With features like AI-generated images, real-time updates, and a tagging system, it provides a unique and engaging way to capture and organize your thoughts.

## Features

- Post messages with optional tags
- Generate images using AI (powered by Stability AI)
- Real-time updates for new messages and comments
- Comment on messages
- React to messages with emojis
- Filter messages by tags
- View popular tags

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Python 3.7 or higher
- A Stability AI API key

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/rad-message-board.git
   cd rad-message-board
   ```

2. Create a virtual environment and activate it:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root and add your Stability AI API key:
   ```
   STABILITY_API_KEY=your_api_key_here
   ```

## Usage

1. Start the application:
   ```
   python app.py
   ```

2. Open a web browser and navigate to `http://localhost:5000`

3. Start posting messages, adding comments, and generating images!

## Customization

You can customize the appearance of the message board by modifying the CSS in the `BASE_HTML` variable in `app.py`.

## Security Notes

- This application is designed for personal use and lacks user authentication.
- The development server provided by Flask should not be used in a production environment.
- Ensure to keep your `.env` file secure and do not expose your API key.

## Contributing

Contributions to the Rad Message Board are welcome. Please feel free to submit a Pull Request.

## License

This project is open source and available under the [MIT License](LICENSE).

## Contact

If you want to contact me, you can reach me at `your.email@example.com`.

