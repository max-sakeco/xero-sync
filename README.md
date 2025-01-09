# Xero Invoice Sync

A Python application that syncs invoices from Xero to a Supabase database. The application uses OAuth2 for authentication and supports incremental syncing to efficiently update only modified invoices.

## Features

- OAuth2 authentication with Xero
- Incremental syncing of invoices and line items
- Automatic token refresh
- Batch processing for efficient database updates
- Detailed sync logging and error tracking

## Prerequisites

- Python 3.8+
- A Xero account with API access
- A Supabase account and project

## Installation

1. Clone the repository:
```bash
git clone https://github.com/max-sakeco/xero-sync.git
cd xero-sync
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy the example environment file and fill in your credentials:
```bash
cp env.example .env
```

## Environment Variables

Create a `.env` file with the following variables:

```env
XERO_CLIENT_ID=your_client_id
XERO_CLIENT_SECRET=your_client_secret
XERO_REDIRECT_URI=your_redirect_uri
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

## Database Setup

1. Create the required tables in your Supabase database by running the SQL in `schema.sql`

## Usage

### Initialize Xero Authentication

```bash
python main.py --init-auth
```

This will provide a URL to authorize the application. Visit the URL, authorize the app, and copy the callback URL.

Then run:
```bash
python main.py --init-auth --callback-url "your_callback_url"
```

### Run a Sync

To sync invoices:
```bash
python main.py --sync-now
```

For a full sync (ignoring last sync time):
```bash
python main.py --sync-now --force-full
```

## Development

The project structure:

- `main.py`: Entry point and command-line interface
- `xero_client.py`: Xero API client implementation
- `supabase_client.py`: Supabase database client
- `sync_manager.py`: Core sync logic
- `schema.sql`: Database schema

## License

MIT License
