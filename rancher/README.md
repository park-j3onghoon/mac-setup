# Rancher Desktop 자동 종료

Rancher Desktop의 VM은 쓰지 않을 때도 메모리를 잡고 있다. `idle_stop.py`는 launchd가 10분마다 실행해서, VM이 도는데 컨테이너도 `docker`·`docker-compose`·`rdctl` 명령도 없는 상태가 30분 이어지면 Rancher Desktop을 끈다.

- 앱이 떠 있으면 `rdctl shutdown`으로 앱과 VM을 같이 끈다. 앱이 죽고 VM만 남았으면 `limactl stop 0`으로 VM만 끈다.
- VM을 다시 켰으면 그 시각부터 센다. 지난번 기록이 오래됐다고 켜자마자 끄지 않는다.
- 다시 쓸 때는 `rdctl start`로 켠다(약 1분).
- `restart=always` 컨테이너가 있으면 늘 사용 중으로 보여 꺼지지 않는다. 계속 띄울 필요가 없으면 `docker update --restart=no <이름>`으로 바꾼다.

```sh
/usr/bin/python3 ~/git/mac-setup/rancher/idle_stop.py install   # 설치·다시 설치 (로그: ~/Library/Logs/rancher-idle-stop.log)
launchctl bootout gui/$(id -u)/local.rancher-idle-stop && rm ~/Library/LaunchAgents/local.rancher-idle-stop.plist   # 제거
cd ~/git/mac-setup/rancher && /usr/bin/python3 -m unittest -v test_idle_stop   # 테스트
```
