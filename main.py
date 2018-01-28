import sys
import json
import socket
import threading
from email.utils import formatdate
import os
from socket import timeout
import magic


def read_config_file(pathToConfigFile):
	data_file = open(pathToConfigFile, "r")
	data = json.load(data_file)
	data_file.close()
	return data

def parse_request(request, config_data):
	fields = request.split(b'\r\n')
	requestLine = fields[0].decode('utf-8').split(' ')
	method = requestLine[0].upper()
	url = requestLine[1]
	version = requestLine[2]
	header = {}
	for field in fields[1:]:
		if(len(field.decode('utf-8')) <1):
			break
		key,value = field.decode('utf-8').lower().split(':', 1)
		header[key] = value[1:]
	return (method, url, version, header)


def send_bad_req_response(status, version, connection, connectionSocket, message):
	statusLine = version + " "+ status+ " "+"\r\n"
	headerLines = "connection:"+" "+connection + "\r\n"
	headerLines+= "date: "+formatdate(timeval=None, localtime=False, usegmt=True)+"\r\n"
	headerLines+="derver: "+"MChon"+"\r\n"
	headerLines += "\r\n" 
	connectionSocket.sendall((statusLine+headerLines+message).encode())

def send_404_response(version, connection, connectionSocket):
	statusLine = version + " "+ "404"+ " "+ "Not Found"+"\r\n"
	headerLines = "connection:"+" "+connection + "\r\n"
	headerLines+= "date: "+formatdate(timeval=None, localtime=False, usegmt=True)+"\r\n"
	headerLines+="derver: "+"MChon"+"\r\n"
	headerLines += "\r\n" 
	connectionSocket.sendall((statusLine+headerLines+"REQUESTED DOMAIN NOT FOUND").encode())



def send_OK_response(method, version, connection, requestedFilePath, requestedFile, connectionSocket):
	statusLine = version+" "+"200 "+"OK" + "\r\n"
	headerLines = "connection: "+connection+"\r\n"
	headerLines+= "date: "+formatdate(timeval=None, localtime=False, usegmt=True)+"\r\n"
	headerLines+="server: MChon"+"\r\n"
	headerLines+="etag: 314"+"\r\n"
	headerLines+="last-modified: "+ formatdate(os.path.getmtime(requestedFilePath), False, True) + "\r\n"
	headerLines+="content-length: "+str(os.path.getsize(requestedFilePath))+ "\r\n"
	headerLines+="content-type: "+str(magic.from_file(requestedFilePath, mime=True)) + "\r\n"
	headerLines+="keep-alive: "+"timeout=5, max=1000"+"\r\n"
	headerLines+="accept-ranges: "+"bytes"+"\r\n"
	connectionSocket.sendall((statusLine+headerLines).encode())
	if(method == "GET"):
		connectionSocket.sendall("\r\n".encode())
		connectionSocket.sendfile(requestedFile)



def send_416_response(fileSize, version, connection, connectionSocket):
	statusLine = version + " "+ "416 "+"Requested Range Not Satisfiable"+"\r\n"
	headerLines = "connection: "+connection + "\r\n"
	headerLines+= "date: "+formatdate(timeval=None, localtime=False, usegmt=True)+"\r\n"
	headerLines+="server: "+"MChon"+"\r\n"
	headerLines+="content-range: "+"*/"+str(fileSize)+'\r\n'
	connectionSocket.sendall((statusLine+headerLines).encode())


def send_partial_content_response(method, version, connection, videoRange, requestedFilePath, requestedFile, connectionSocket):
	unitRange = videoRange.split("=")[0]
	startAndEnd = videoRange.split("=")[1] 
	startRange = int(startAndEnd.split("-")[0])
	endRange = startAndEnd.split("-")[1]
	fileSize = os.path.getsize(requestedFilePath)
	data = None
	if endRange == "":
		endRange = fileSize-1
	else:
		endRange = int(endRange)
	if startRange > endRange or startRange>=fileSize or endRange>=fileSize:
		send_416_response(fileSize, version, connection, connectionSocket)
		return
	
	try:
		requestedFile.seek(startRange, 0)
	except Exception as e:
		# print(e)
		send_416_response(version, connection, connectionSocket)
		return
	
	data = requestedFile.read(endRange - startRange+1)

	statusLine = version+" 206 Partial Content" + "\r\n"
	headerLines = "connection: "+connection+"\r\n"
	headerLines+= "date: "+formatdate(timeval=None, localtime=False, usegmt=True)+"\r\n"
	headerLines+="server: MChon"+"\r\n"
	headerLines+="etag: 314"+"\r\n"
	headerLines+="last-modified: "+ formatdate(os.path.getmtime(requestedFilePath), False, True) + "\r\n"
	headerLines+="content-length: "+ str(endRange - startRange+1) + "\r\n"
	headerLines+="content-type: "+str(magic.from_file(requestedFilePath, mime=True)) + "\r\n"
	headerLines+="keep-alive: "+"timeout=5, max=1000"+"\r\n"
	headerLines+="accept-ranges: "+"bytes"+"\r\n"
	headerLines+="content-range: bytes "+ str(startRange)+'-'+str(endRange)+'/'+str(fileSize) + "\r\n"
	connectionSocket.sendall((statusLine+headerLines).encode())
	if(method == "GET"):
		connectionSocket.sendall("\r\n".encode())
		connectionSocket.sendall(data)






def generate_response(request, config_data, connectionSocket):
	method = request[0]
	url = request[1]
	version = request[2]
	headers = request[3]
	host = headers["host"].split(":")[0]
	connection = headers["connection"]
	if method.lower() not in ["get", "head"]:
		send_bad_req_response("400 Bad Request", version, connection, connectionSocket, "Invalid Request Message Framing")

	requestedFilePath = ""	

	#Checking whether requested host is on my server 
	domainNotFound = True
	for vh in config_data:	#case when host is example1.com:8080 needs split
		if vh["vhost"] == host:
			domainNotFound = False
			requestedFilePath = vh["documentroot"]
			break
	
	#Domain not found 
	if domainNotFound:
		send_404_response(version, connection, connectionSocket)
		return connection# return False
	#Domain found
	requestedFilePath=requestedFilePath + url
	requestedFilePath = requestedFilePath.replace('%20', " ").strip()
	try:
		requestedFile = open(requestedFilePath, 'rb')
	except Exception as e:
		send_404_response(version, connection, connectionSocket)
		return connection

	if "range" in headers:
		send_partial_content_response(method, version, connection, headers["range"], requestedFilePath, requestedFile, connectionSocket)
		requestedFile.close()
		return connection
	send_OK_response(method, version, connection, requestedFilePath, requestedFile, connectionSocket)
	requestedFile.close()
	return connection



def serve(connectionSocket, address, config_data):
	while 1:
		# connectionSocket.settimeout(5)
		try:
			req = connectionSocket.recv(65000)
			# connectionSocket.settimeout(None)
		except Exception as e:
			# print(e)
			break
		if(req is None or req.decode('utf-8') == ""):
			break
		req_info = parse_request(req, config_data)
		resp = generate_response(req_info, config_data, connectionSocket)
		if resp == "close":
			break
		elif resp == "keep-alive":
			connectionSocket.settimeout(5)
	connectionSocket.close()


def create_socket(ip, port, config_data):
	serverSocket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
	serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	serverSocket.bind((ip, port))
	serverSocket.listen(1024)
	while 1 :
		connectionSocket, addr = serverSocket.accept()
		t = threading.Thread(target = serve, args=(connectionSocket, addr, config_data, ))
		t.start()






if __name__ == "__main__":
	config_data = read_config_file(sys.argv[1])
	#Create sockets for each virtual host port
	# serverThreads = []
	ipAndPorts = []
	#should not create new thread for the same ip-port
	for vhostInfo in config_data["server"]:
		ip = vhostInfo['ip']
		port = int(vhostInfo['port'])
		if (ip, port) not in ipAndPorts:
			ipAndPorts.append((ip, port))
			t = threading.Thread(target=create_socket, args=(ip, port, config_data["server"],))
			# serverThreads.append(t)
			t.start()
