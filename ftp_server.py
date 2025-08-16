import os
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

def main():
    authorizer = DummyAuthorizer()

   
    ftp_root_dir = os.path.join(os.getcwd(), "ftp_root")
    os.makedirs(ftp_root_dir, exist_ok=True)
    
   
    authorizer.add_user(
        "ezaz",
        "password123",
        ftp_root_dir,  
        perm="elradfmwMT" 
    )

    # --- Anonymous User (Guest) Setup ---
    authorizer.add_anonymous(
        ftp_root_dir, 
        perm="elr"    
    )
    
    # --- Configure and Start Server
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "Welcome to OS Project FTP Server (Admin Full Control)."
    
    address = ("0.0.0.0", 2121)
    server = FTPServer(address, handler)
    server.max_cons = 256
    server.max_cons_per_ip = 5

    print(f"Starting FTP server on {address[0]}:{address[1]}...")
    server.serve_forever()

if __name__ == "__main__":
    main()