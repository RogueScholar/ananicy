#!/usr/bin/env python3

import os
import re
import sys
import subprocess
import json
import _thread

from time import sleep


class Failure(Exception):
    pass


class Ananicy:
    config_dir = None
    types = {}
    rules = {}

    proc = {}

    def __init__(self, config_dir="/etc/ananicy.d/", check_sched=True):
        if check_sched:
            self.__check_disks_schedulers()
        self.dir_must_exits(config_dir)
        self.config_dir = config_dir
        self.load_types()
        self.load_rules()
        if os.getenv("NOTIFY_SOCKET"):
            self.run_cmd(["systemd-notify", "--ready"])

    def __strip_line(self, line):
        line = line.rstrip()
        # Remove comments from input
        line = line.split('#')
        return line[0]

    def __get_val(self, col):
        tmp = col.split('=')
        if len(tmp) < 1:
            return ""
        return tmp[1].rstrip('"')

    def __check_nice(self, nice):
        if nice > 19 or nice < -20:
            raise Failure("Nice must be in range -20..19")

    def __check_ionice(self, ionice):
        if ionice > 7 or ionice < 0:
            raise Failure("IOnice/IOprio allowed only in range 0-7")

    def __check_oom_score_adj(self, adj):
        if adj < -1000 or adj > 1000:
            raise Failure("OOM_SCORE_ADJ must be in range -1000..1000")

    def __check_disks_schedulers(self):
        prefix = "/sys/class/block/"
        for disk in os.listdir(prefix):
            if re.search('loop', disk):
                continue
            if re.search('ram', disk):
                continue
            if re.search('sr', disk):
                continue
            scheduler = prefix + disk + "/queue/scheduler"
            if not os.path.exists(scheduler):
                continue
            with open(scheduler) as fd:
                c_sched = fd.readlines()
                c_sched = c_sched[0].rstrip()
                if re.search('\\[cfq\\]', c_sched):
                    continue
                if re.search('\\[bfq\\]', c_sched):
                    continue
                if re.search('\\[bfq-mq\\]', c_sched):
                    continue
            print("Disk {} not use cfq/bfq scheduler IOCLASS/IONICE will not work on it".format(disk))

    def get_type_info(self, line):
        line = self.__strip_line(line)
        if len(line) < 2:
            return

        name = ""
        nice = ""
        ioclass = ""
        ionice = ""
        sched = ""
        oom_score_adj = ""

        line = line.split()
        for col in line:
            if "TYPE=" in col:
                name = self.__get_val(col)
            if "NICE=" in col:
                if "IONICE=" in col:
                    ionice = int(self.__get_val(col))
                    self.__check_ionice(ionice)
                else:
                    nice = int(self.__get_val(col))
                    self.__check_nice(nice)
            if "IOCLASS=" in col:
                ioclass = self.__get_val(col)

            if "SCHED=" in col:
                sched = self.__get_val(col)
            if "OOM_SCORE_ADJ=" in col:
                oom_score_adj = int(self.__get_val(col))
                self.__check_oom_score_adj(oom_score_adj)

        if name == "":
            raise Failure("Missing TYPE=")

        self.types[name] = {
            "nice": nice,
            "ioclass": ioclass,
            "ionice": ionice,
            "sched": sched,
            "oom_score_adj": oom_score_adj
        }

    def load_types(self):
        type_files = self.find_files(self.config_dir, '.*\\.types')
        for file in type_files:
            with open(file) as fd:
                for line in fd.readlines():
                    try:
                        self.get_type_info(line)
                    except Failure as e:
                        print(file, e)

    def get_rule_info(self, line):
        line = self.__strip_line(line)
        if len(line) < 2:
            return

        name = ""
        nice = ""
        ioclass = ""
        ionice = ""
        sched = ""
        oom_score_adj = ""

        line = line.split()
        for col in line:
            if "NAME=" in col:
                name = self.__get_val(col)
            if "TYPE=" in col:
                type = self.__get_val(col)
                type = self.types[type]
                nice = type.get("nice")
                ioclass = type.get("ioclass")
                ionice = type.get("ionice")
                sched = type.get("sched")
                oom_score_adj = type.get("oom_score_adj")
            if "NICE=" in col:
                if "IONICE=" in col:
                    ionice = self.__get_val(col)
                    if ionice:
                        ionice = int(ionice)
                        self.__check_ionice(ionice)
                else:
                    nice = self.__get_val(col)
                    if nice:
                        nice = int(nice)
                        self.__check_nice(nice)
            if "IOCLASS=" in col:
                ioclass = self.__get_val(col)
            if "SCHED=" in col:
                sched = self.__get_val(col)
            if "OOM_SCORE_ADJ=" in col:
                oom_score_adj = int(self.__get_val(col))
                self.__check_oom_score_adj(oom_score_adj)

        if name == "":
            raise Failure("Missing NAME=")

        self.rules[name] = {
            "nice": nice,
            "ioclass": ioclass,
            "ionice": ionice,
            "sched": sched,
            "oom_score_adj": oom_score_adj
        }

    def load_rules(self):
        rule_files = self.find_files(self.config_dir, '.*\\.rules')
        for file in rule_files:
            with open(file) as fd:
                for line in fd.readlines():
                    try:
                        self.get_rule_info(line)
                    except Failure as e:
                        print(file + ":", e)

        if len(self.rules) == 0:
            raise Failure("No rules loaded")

    def dir_must_exits(self, path):
        if not os.path.exists(path):
            raise Failure("Missing dir: " + path)

    def run_cmd(self, run):
        ret = subprocess.run(run, timeout=30, check=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             universal_newlines=True
                             )
        return ret

    def find_files(self, path, name_mask):
        files = []
        entryes = os.listdir(path)
        if len(entryes) == 0:
            return files
        for entry_name in entryes:
            entry_path = path + "/" + entry_name
            if os.path.isdir(entry_path):
                files += self.find_files(entry_path, name_mask)
            if os.path.isfile(entry_path):
                if re.search(name_mask, entry_name):
                    files += [entry_path]
        return files

    def update_proc_map(self):
        proc = {}
        for proc_dir in os.listdir("/proc"):
            try:
                pid = int(proc_dir)
                task_dirs = os.listdir("/proc/" + str(pid) + "/task/")
                exe = os.path.realpath("/proc/" + str(pid) + "/exe")
                _oom_score_adj = open("/proc/" + str(pid) + "/oom_score_adj").readline()
                oom_score_adj = int(_oom_score_adj.rstrip())
            except ValueError:
                continue
            except FileNotFoundError:
                continue
            _exe = exe.split('/')
            cmd = _exe[-1]
            for task_dir in task_dirs:
                try:
                    tpid = int(task_dir)
                except ValueError:
                    continue
                stat = ""
                cmdline = ""
                nice = ""
                try:
                    stat = open("/proc/" + str(pid) + "/task/" + str(tpid) + "/stat").readline().rstrip()
                    m = re.search('\\) . .*', stat)
                    m = m.group(0)
                    m = m.rsplit()
                    nice = int(m[17])

                    cmdline = open("/proc/" + str(pid) + "/task/" + str(tpid) + "/cmdline").readline().rstrip('\x00')
                    cmdline = cmdline.replace('\u0000', ' ')
                except FileNotFoundError:
                    continue

                proc[tpid] = {
                    'tpid': tpid,
                    'exe': exe,
                    'cmd': cmd,
                    'nice': nice,
                    'oom_score_adj': oom_score_adj,
                    'stat': stat,
                    'cmdline': cmdline,
                }
        self.proc = proc

    def thread_update_proc_map(self, pause=1):
        while True:
            self.update_proc_map()
            sleep(pause)

    def renice(self, proc, pid, nice):
        try:
            self.run_cmd(["renice", "-n", str(nice), "-p", str(pid)])
        except subprocess.CalledProcessError:
            return
        msg = "renice: {}[{}] {} -> {}".format(proc[pid]["cmd"], pid, proc[pid]["nice"], nice)
        print(msg)

    def get_ioclass(self, pid):
        ret = self.run_cmd(["ionice", "-p", str(pid)])
        stdout = ret.stdout.rsplit(': prio ')
        return stdout[0].rstrip()

    def get_ionice(self, pid):
        ret = self.run_cmd(["ionice", "-p", str(pid)])
        stdout = ret.stdout.rsplit(': prio ')
        return stdout[1].rstrip()

    def ioclass(self, proc, pid, ioclass):
        try:
            c_ioclass = self.get_ioclass(pid)
            if ioclass != c_ioclass:
                self.run_cmd(["ionice", "-p", str(pid), "-c", ioclass])
                msg = "ioclass: {}[{}] {} -> {}".format(proc[pid]["cmd"], pid, c_ioclass, ioclass)
                print(msg)
        except subprocess.CalledProcessError:
            return

    def ionice(self, proc, pid, ionice):
        try:
            c_ionice = self.get_ionice(pid)
            if str(ionice) != c_ionice:
                self.run_cmd(["ionice", "-p", str(pid), "-n", str(ionice)])
                msg = "ionice: {}[{}] {} -> {}".format(proc[pid]["cmd"], pid, c_ionice, ionice)
                print(msg)
        except subprocess.CalledProcessError:
            return

    def get_oom_score_adj(self, pid):
        _oom_score_adj = open("/proc/" + str(pid) + "/oom_score_adj").readline().rstrip()
        return int(_oom_score_adj)

    def oom_score_adj(self, proc, pid, oom_score_adj):
        try:
            c_oom_score_adj = self.get_oom_score_adj(pid)
            if c_oom_score_adj != oom_score_adj:
                file = open("/proc/" + str(pid) + "/oom_score_adj")
                file.write(str(oom_score_adj))
                msg = "oom_score_adj: {}[{}] {} -> {}".format(proc[pid]["cmd"], pid, c_oom_score_adj, oom_score_adj)
                print(msg)
        except FileNotFoundError:
            return

    def get_sched(self, pid):
        try:
            ret = self.run_cmd(["schedtool", str(pid)])
            if "ERROR" in ret.stdout.rstrip():
                return
            sched = ret.stdout.rstrip()
            sched = sched.rsplit(',')
            sched = sched[1]
            sched = sched.rstrip(' ').rsplit(': ')[1]
            sched = sched.rsplit('_')[1]
            sched = sched.lower()
            return sched
        except subprocess.CalledProcessError:
            return

    def sched(self, proc, pid, sched):
        l_prio = 0
        arg_map = {
            'other': '-N',
            'normal': '-N',
            'rr': '-R',
            'fifo': '-F',
            'batch': '-B',
            'iso': '-I',
            'idle': '-D'
        }
        c_sched = self.get_sched(pid)
        if not c_sched:
            return
        if c_sched == sched:
            return
        if sched == "other" and c_sched == "normal":
            return
        if sched == "idle" and c_sched == "idleprio":
            return
        if sched == "rr" or sched == "fifo":
            l_prio = 1
        sched_arg = arg_map[sched]
        try:
            self.run_cmd(["schedtool", sched_arg, "-p", str(l_prio), str(pid)])
        except subprocess.CalledProcessError:
            return

    def process_pid(self, proc, pid):
        proc_entry = proc[pid]
        cmd = proc_entry["cmd"]
        rule = self.rules.get(cmd)
        if not rule:
            return
        current_nice = proc_entry["nice"]
        if rule.get("nice"):
            if current_nice != rule["nice"]:
                self.renice(proc, pid, rule["nice"])
        if rule.get("ioclass"):
            self.ioclass(proc, pid, rule["ioclass"])
        if rule.get("ionice"):
            self.ionice(proc, pid, rule["ionice"])
        if rule.get("sched"):
            self.sched(proc, pid, rule["sched"])
        if rule.get("oom_score_adj"):
            self.oom_score_adj(proc, pid, rule["oom_score_adj"])

    def processing_rules(self):
        proc = self.proc
        for pid in proc:
            self.process_pid(proc, pid)

    def run(self):
        _thread.start_new_thread(self.thread_update_proc_map, (1,))
        while True:
            self.processing_rules()
            sleep(1)

    def dump_types(self):
        print(json.dumps(self.types, indent=4), flush=True)

    def dump_rules(self):
        print(json.dumps(self.rules, indent=4), flush=True)

    def dump_proc(self):
        self.update_proc_map()
        print(json.dumps(self.proc, indent=4), flush=True)


def help():
    print("Usage: ananicy [options]\n",
          "  start         Run script\n",
          "  stop          Stop script\n",
          "  reload        Recompile rule cache\n",
          "  dump rules    Generate and print rules cache to stdout\n",
          "  dump types    Generate and print types cache to stdout\n",
          "  dump proc     Generate and print proc map cache to stdout")
    exit(0)


def main(argv):

    if len(argv) < 2:
        help()

    if argv[1] == "start":
        daemon = Ananicy()
        daemon.run()

    if argv[1] == "dump":
        daemon = Ananicy(check_sched=False)
        if argv[2] == "rules":
            daemon.dump_rules()
        if argv[2] == "types":
            daemon.dump_types()
        if argv[2] == "proc":
            daemon.dump_proc()


if __name__ == '__main__':
    main(sys.argv)