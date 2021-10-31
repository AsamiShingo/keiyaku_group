from flask import Flask, url_for, redirect, send_file
from flask import request
from flask import jsonify
from flask import render_template
from werkzeug.utils import secure_filename
import os
import glob
import re
import threading
import json
import numpy as np
import datetime
from keiyakudata import KeiyakuData
from keiyakumodelfactory import KeiyakuModelFactory

DATA_DIR = os.path.join(os.path.dirname(__file__), r"data")
ANALYZE_DIR = os.path.join(os.path.dirname(__file__), r"analyze")
keiyaku_analyze_mutex = threading.Lock()

class KeiyakuWebData:
    
    PARA_FILE = "param.json"

    create_seqid_mutex = threading.Lock()        

    def __init__(self, seqid=None, orgfilename="", mimetype=""):
        if seqid != None:
            self.seqid = seqid
            self.paradata = {}

            with open(os.path.join(self.get_dirpath(), self.PARA_FILE), "r") as parafile:
                para = json.load(parafile)
                self.paradata["orgfilename"] = para["orgfilename"]
                self.paradata["filename"] = para["filename"]
                self.paradata["txtname"] = para["txtname"]
                self.paradata["csvname"] = para["csvname"]
                self.paradata["mimetype"] = para["mimetype"]
        else:
            if orgfilename == "" or mimetype == "":
                raise AttributeError()

            self.seqid = self._create_seqid()
            self.paradata = {}
            
            filename = secure_filename(orgfilename)
            self.paradata["orgfilename"] = orgfilename
            self.paradata["filename"] = filename
            self.paradata["txtname"] = "txt_{}.txt".format(os.path.basename(filename))
            self.paradata["csvname"] = "csv_{}.csv".format(os.path.basename(filename))
            self.paradata["mimetype"] = mimetype
            with open(os.path.join(self.get_dirpath(), self.PARA_FILE), "w") as parafile:
                json.dump(self.paradata, parafile, ensure_ascii=False, indent=4)

    def get_dirpath(self):
        return os.path.join(DATA_DIR, self.seqid)

    def get_orgfilename(self):
        return self.paradata["orgfilename"]

    def get_orgtxtname(self):
        return os.path.basename(self.get_orgfilename()) + ".txt"

    def get_filename(self):
        return self.paradata["filename"]

    def get_filepath(self):
        return os.path.join(self.get_dirpath(), self.get_filename())

    def get_txtname(self):
        return self.paradata["txtname"]

    def get_txtpath(self):
        return os.path.join(self.get_dirpath(), self.get_txtname())

    def get_csvname(self):
        return self.paradata["csvname"]

    def get_csvpath(self):
        return os.path.join(self.get_dirpath(), self.get_csvname())

    def get_mimetype(self):
        return self.paradata["mimetype"]

    def create_analyzepath(self):
        analyze_dir = os.path.join(ANALYZE_DIR, self.seqid)
        os.makedirs(analyze_dir, exist_ok=True)
        return os.path.join(analyze_dir, datetime.datetime.now().strftime('%Y%m%d%H%M%S') + ".txt")

    def _create_seqid(self):
        self.create_seqid_mutex.acquire()

        dirs = glob.glob(os.path.join(DATA_DIR, r"?????"))
        dirs = [os.path.basename(dir) for dir in dirs if os.path.isdir(dir)]
        seqs = [int(seq) for seq in dirs if re.match(r'[0-9]{5}', seq)]
        seq = str(max(seqs) + 1) if len(seqs) != 0 else "0"

        seqid = seq.zfill(5)
        os.mkdir(os.path.join(DATA_DIR, seqid))

        self.create_seqid_mutex.release()

        return seqid

def keiyaku_analyze(csvpath):
    keiyaku_analyze_mutex.acquire()

    keiyakumodel, model, tokenizer = KeiyakuModelFactory.get_keiyakumodel()    
    keiyakudata = KeiyakuData(csvpath)
    predict_datas = keiyakudata.get_group_datas(tokenizer, model.seq_len)
    score1, score2 = keiyakumodel.predict(predict_datas)

    keiyaku_analyze_mutex.release()
    
    return score1, score2

app = Flask(__name__)

def init_web(debugmode):
    if debugmode == False:
        KeiyakuModelFactory.get_keiyakumodel()
        
    app.run(debug=debugmode, host="0.0.0.0", port=80)
    
@app.route("/keiyaku_group/")
def index():
    datas = []
    for dir in glob.glob(os.path.join(DATA_DIR, r"?????")):
        seqid = os.path.basename(dir)
        data = KeiyakuWebData(seqid)

        if os.path.isfile(data.get_filepath()):
            datas.append((seqid, data.get_orgfilename()))

    return render_template("index.html", datas=datas)

@app.route("/keiyaku_group/upload", methods=["POST"])
def upload():
    f = request.files["file"]
    data = KeiyakuWebData(orgfilename=f.filename, mimetype=request.mimetype)
    
    f.save(data.get_filepath())
    KeiyakuData.create_keiyaku_data(data.get_filepath(), data.get_txtpath(), data.get_csvpath())

    return redirect(url_for("index"))

@app.route("/keiyaku_group/download", methods=["POST"])
def download():
    seqid = request.form["seqid"]
    data = KeiyakuWebData(seqid)
    return send_file(data.get_filepath(), as_attachment=True, attachment_filename=data.get_orgfilename())

@app.route("/keiyaku_group/delete", methods=["POST"])
def delete():
    seqid = request.form["seqid"]
    data = KeiyakuWebData(seqid)

    dirpath = data.get_dirpath()
    if os.path.isdir(dirpath) == False:
        raise FileNotFoundError("{}のディレクトリが存在しません".format(dirpath))

    for delfile in os.listdir(dirpath):
        os.remove(os.path.join(dirpath, delfile))

    os.rmdir(dirpath)

    return redirect(url_for("index"))

@app.route("/keiyaku_group/analyze_txt", methods=["POST"])
def analyze_txt():
    seqid = request.form["seqid"]
    data = KeiyakuWebData(seqid)
    
    scores1, scores2 = keiyaku_analyze(data.get_csvpath())
    keiyakudata = KeiyakuData(data.get_csvpath())
    sentensedatas = keiyakudata.get_datas()
    analyze_path = data.create_analyzepath()

    np.set_printoptions(precision=2, floatmode='fixed')
    with open(analyze_path, "w") as f:
        for sentensedata, score1, score2 in zip(sentensedatas, scores1, scores2):
            sentense = sentensedata[6]
            kind1 = score2.argmax()
            if score1 >= 0.5:
                f.write("{}---------------------------------------------\n".format(score1))
                
            f.write("{}-{:0.2f}:{}\n".format(kind1, score2[kind1], sentense))

    return send_file(analyze_path, as_attachment=True, attachment_filename=data.get_orgtxtname())

@app.route("/keiyaku_group/analyze_json", methods=["POST"])
def analyze_json():
    seqid = request.form["seqid"]
    data = KeiyakuWebData(seqid)

    scores1, scores2 = keiyaku_analyze(data.get_csvpath())
    
    jsondata = {}
    for col, score in enumerate(zip(scores1, scores2)):
        score1 = score[0]
        score2 = score[1]
        scoredata = {}
        scoredata[1] = round(float(score1[0]), 2)
        scoredata[2] = { i:round(float(score), 2) for i, score in enumerate(score2) }
        jsondata[col] = scoredata

    return jsonify(jsondata)