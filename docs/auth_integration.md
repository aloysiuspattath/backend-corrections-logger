# External Authentication Integration Guide

The Backend Corrections Portal natively supports external user authentication alongside local super-admins. The `bcp_users` table includes two special columns to facilitate this:
- `is_external` (NUMBER 1 or 0): Identifies if the user is managed externally.
- `auth_source` (VARCHAR2): Identifies the source (e.g., `'local'`, `'ad'`, `'external_oracle'`).

External users cannot change their passwords via the portal (the UI automatically hides the password change form for them).

Below are the architectural patterns used in `auth.py` to connect your portal to Active Directory or an external Oracle Database.

---

## 1. Active Directory (AD) / LDAP Integration

To authenticate users against your corporate Active Directory, the application uses the `ldap3` Python library (which is bundled in the `vendor/` directory for offline installations).

### Configuration
Update the `auth_ad` function in `auth.py` with your Active Directory server and domain details. If configured correctly, the system will perform the following during a login attempt:

1. Attempt to bind to the AD server using the provided username and password.
2. If successful, it automatically provisions the user into the `bcp_users` table with `is_external=1` and `auth_source='ad'`.
3. The user is instantly logged into the portal as a standard User.

> **Security Best Practice:** The portal never stores AD passwords in the local database. The `password_hash` column is left `NULL` for external users.

---

## 2. External Oracle Database Integration

If your user credentials and roles are managed in a completely separate Oracle Database (like a central HR system or ERP), the easiest and recommended approach is to use a **Database Link**.

### Implementation (Database Link)
This method requires absolutely no Python code changes.

1. **Create the DB Link** in your portal's Oracle database pointing to the external database:
   ```sql
   CREATE DATABASE LINK central_db 
   CONNECT TO external_user IDENTIFIED BY ext_password 
   USING 'central_db_tns';
   ```

2. **Create a Database VIEW** that maps the remote user table into the `bcp_users` structure:
   ```sql
   CREATE OR REPLACE VIEW bcp_users AS
   SELECT 
       id, 
       username, 
       password_hash, 
       display_name, 
       role, 
       1 AS is_external, 
       'external_oracle' AS auth_source 
   FROM central_users@central_db;
   ```

3. The Python backend will now query the view exactly as if it were querying a local table, completely abstracting the remote connection logic.

> **Network Note:** When integrating external databases, ensure your network security groups and firewalls permit traffic on port 1521 between the application server and the external Oracle Database.
