# Interoperable and Modular HDT System Prototype

This project provides a prototype of an interoperable and modular **Human Digital Twins (HDT)** system architecture.

Interoperability refers to the system's ability to access, synthesize, and standardize health data from diverse applications and platforms such as GameBus and Google Fit. These capabilities allow external model developers to efficiently locate and utilize the exact data they need for building models.

Modularity refers to the system's capacity to support the open development, testing, and integration of various virtual twin models. This flexibility encourages collaboration and facilitates the extension of the system with new functionalities.

This prototype establishes a solid foundation for future expansion and improvement. To foster further development, this public repository is intended to serve as a collaborative resource for researchers and developers interested in advancing such systems.

For detailed information about the project, please refer to the associated master's thesis paper [Thesis Paper (06-12-24 V2)](docs/Thesis%20paper%2006-12-24%20V2.pdf), titled:

**"Designing an Interoperable and Modular System Architecture to Support the Development of Human Digital Twins for Promoting Healthy Lifestyle Behaviors"**



The remainder of this README provides detailed information about the system components and instructions for deployment.

## Table of Contents
- [System Architecture](#system-architecture)
  - [Subfolder Dependencies and Functions](#subfolder-dependencies-and-functions)
- [API Documentation](#api-documentation)
- [Setup and Installation](#setup-and-installation)
  - [Prerequisites](#prerequisites)
  - [Environment Setup](#environment-setup)
- [Configuration](#configuration)
  - [External APIs (GameBus, Google Fit)](#external-apis-gamebus-google-fit)
  - [User Permissions](#user-permissions)
- [Usage](#usage)
  - [Running the API](#running-the-api)
  - [Interacting with the API](#interacting-with-the-api)
- [How Components Interact](#how-components-interact)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## System Architecture

### Subfolder Dependencies and Functions

#### **`config` Subfolder**
- **Purpose**: Centralizes configurations, API keys, external party definitions, and user permissions.
- **Key Files**:
  - `.env`: Stores API keys for secure access.
  - `config.py`: Loads API keys and permissions, with error handling for missing configurations.
  - `external_parties.json`: Defines external clients with their `client_id`s.
  - `user_permissions.json`: Maps user IDs to allowed external clients and their permitted actions.
  - `users.json`: Provides details about users, including their connected apps for each health domain and the associated authentication tokens.

#### **`HDT_CORE_INFRASTRUCTURE` Subfolder**
- **Purpose**: Handles data fetching, parsing, authentication, and API exposure (to be extended with more available data sources and API endpoints).
- **Key Files**:
  - `auth.py`: Implements an authentication and authorization decorator based on API keys, user permissions, and required actions.
  - `GAMEBUS_DIABETES_fetch.py`: Fetches Trivia and SugarVita from the GameBus API.
  - `GAMEBUS_DIABETES_parse.py`: Contains parsing functions for converting raw responses from GameBus into structured formats.
  - `GAMEBUS_WALK_fetch.py`: Fetches walk from the GameBus API.
  - `GAMEBUS_WALK_parse.py`: Contains parsing functions for converting raw responses from GameBus into structured formats.
  - `GOOGLE_FIT_WALK_fetch`: Fetches Google Fit step count data.
  - `GOOGLE_FIT_WALK_parse`:Contains parsing functions for converting raw responses from Google Fit into structured formats.
  - `HDT_API.py`: Flask app exposing the following endpoints:
    - **for Model Developers**:
      - `/get_trivia_data`: Retrieves standardized trivia playthrough metrics.
      - `/get_sugarvita_data`: Retrieves standardized SugarVita playthrough metrics.
      - `/get_walk_data`: Retrieves standardized walk-related metrics.
    - **for App Developers**:
      - `/get_sugarvita_player_types`: Retrieves SugarVita player type scores.
      - `/get_health_literacy_diabetes`: Retrieves diabetes-related health literacy scores.

#### **`Virtual_Twin_Models` Subfolder**
- **Purpose**: Calculate health literacy and player type scores (to be extended with more diverse models).
- **Key Files**:
  - `HDT_DIABETES_calculations.py`: Contains functions for metric manipulation, normalization, scoring, and player-type determination.
  - `HDT_DIABETES_model.py`: Orchestrates fetching data from APIs, calculating scores, and storing results in `diabetes_pt_hl_storage.json`.

#### **`diabetes_pt_hl_storage.json`**
- **Purpose**: Acts as persistent storage for the model results, including health literacy scores and player types. (In the future, the collection of trained models and resulting outputs will be stored in the cloud, forming the main "Virtual Twin".)

---

## API Documentation

Full documentation for the **HDT API endpoints** is available through Swagger:
[Swagger Documentation](https://pimvanvroonhoven.github.io/Interoperable-and-modular-HDT-system-prototype/)


---

## Setup and Installation

### Prerequisites
1. Python 3.8 or higher.
2. A virtual environment tool like `venv` or `conda`.
3. [Postman](https://www.postman.com/) or cURL (optional, for testing the API).

### Environment Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/YourUsername/Interoperable-and-modular-HDT-system-prototype.git
   cd Interoperable-and-modular-HDT-system-prototype
   ```

2. Set up a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Ensure the `.env` file in the `config` folder contains valid API keys:
   ```plaintext
   MODEL_DEVELOPER_1_API_KEY=your_key_here
   HEALTH_APP_1_API_KEY=your_key_here
   ```

---

## Configuration

### External APIs (GameBus, Google Fit)
To fetch data from external sources, you must populate the `player_id` and `auth_bearer` fields in the `users.json` file (located in the `config` folder). 

- **GameBus API**:
  - Follow the instructions here to obtain your credentials: [GameBus Get Started Guide](https://devdocs.gamebus.eu/get-started/)

- **Google Fit API**:
  - Set up access and retrieve credentials following this guide: [Google Fit API Get Started](https://developers.google.com/fit/rest/v1/get-started)

These credentials are essential for the second round of API calls inside the HDT_API to fetch user-specific data.

---

### User Permissions
The file `user_permissions.json` defines the access permissions for different clients and endpoints. Modify this file to customize access levels.
In the future, this file should be replaced by a proper ui with advanced authentication measures, which each user can use to control access to their data and models.

---

## Usage

### Running the API
1. Start the Flask application:
   ```bash
   python -m HDT_CORE_INFRASTRUCTURE.HDT_API
   ```

2. The API will run on `http://localhost:5000`.

3. In another terminal, start the MCP façade:
`python HDT_MCP/server.py`

4. In another terminal, start the MCP inspector:
`mcp dev HDT_MCP/server.py`
Or with config:
`npx @modelcontextprotocol/inspector --config .\config\mcp.json --server hdt-mcp`


### Interacting with the API
- Use tools like [Postman](https://www.postman.com/) to test the API endpoints.
- Example endpoints:
  - `/get_trivia_data`
  - `/get_sugarvita_data`
  - `/get_walk_data`

Refer to the [Swagger Documentation](https://pimvanvroonhoven.github.io/Interoperable-and-modular-HDT-system-prototype/) for full details.

---

## How Components Interact

1. **Fetching Data**:
   - `HDT_API.py` endpoints call fetch functions from `GAMEBUS_DIABETES_fetch.py`, `GAMEBUS_WALK_fetch.py` or `GOOGLE_FIT_WALK_fetch.py`, based on user permissions and connected apps (retrieved from `users.json`).

2. **Parsing Data**:
   - Fetch functions parse raw API responses using `*_parse.py` files (e.g., `parse_json_trivia`).

3. **Virtual Twin Model calculations**:
   - `HDT_DIABETES_model.py`:
     - Fetches Trivia and SugarVita data via the HDT API endpoints (`get_trivia_data`, `get_sugarvita_data`).
     - Manipulates and normalizes metrics using `HDT_DIABETES_calculations.py`.
     - Calculates health literacy and player type scores.
     - Updates `diabetes_pt_hl_storage.json` with the results.

4. **API Endpoint Input/Output**:
   - **Model Developer APIs**:
     - Inputs: API key (header), optional query params (e.g., `user_id` for filtering).
     - Outputs: Processed metrics, latest activity info, or errors.
   - **App Developer APIs**:
     - Inputs: API key (header), `user_id` (query param).
     - Outputs:
       - `/get_sugarvita_player_types`: Latest player type scores for a user.
       - `/get_health_literacy_diabetes`: Latest health literacy score for a user.

---

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your changes.




