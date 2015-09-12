# -*- coding: utf-8 -*-
from openerp import models, fields, api
import ftplib
import os
import re
import math
from lxml import etree
import types
import datetime
from constants import *
import logging
_logger = logging.getLogger(__name__)

#############################################################################################################
#                                                                                                           #
#                           These two functions are copied from the product model                           #
#                                                                                                           #
#############################################################################################################
def sanitize_ean13(ean13):
    """Creates and returns a valid ean13 from an invalid one"""
    if not ean13:
        return "0000000000000"
    ean13 = re.sub("[A-Za-z]","0",ean13);
    ean13 = re.sub("[^0-9]","",ean13);
    ean13 = ean13[:13]
    if len(ean13) < 13:
        ean13 = ean13 + '0' * (13-len(ean13))
    return ean13[:-1] + str(ean_checksum(ean13))

def ean_checksum(eancode):
    """returns the checksum of an ean string of length 13, returns -1 if the string has the wrong length"""
    if len(eancode) != 13:
        return -1
    oddsum=0
    evensum=0
    total=0
    eanvalue=eancode
    reversevalue = eanvalue[::-1]
    finalean=reversevalue[1:]
    
    for i in range(len(finalean)):
        if i % 2 == 0:
            oddsum += int(finalean[i])
        else:
            evensum += int(finalean[i])
    total=(oddsum * 3) + evensum
    
    check = int(10 - math.ceil(total % 10.0)) %10
    return check

#############################################################################################################

class cwa_import_module(models.Model):
    _name = 'cwa.import'
        
    def connect_to_ftp(self, address, usr, pwd):
        ftp = ftplib.FTP(address)
        ftp.login(usr, pwd)
        return ftp
    
    def disconnect_from_ftp(self, ftp):
        ftp.quit()
        return True
        
    def download_ftp_files(self, tmp, ftp, todo, done):
        ftp.cwd(done)
        processed_files = ftp.nlst()
        ftp.cwd(todo)
        todo_files = ftp.nlst()
        if not os.path.exists('/tmp/%s' % tmp):
            os.mkdir('/tmp/%s' % tmp)
        for f in todo_files:
            if f not in processed_files:
                ftp.retrbinary("RETR %s" % f, open('/tmp/%s/%s' % (tmp, f), 'wb').write)     
        return True
    
    def move_ftp_files(self, tmp, ftp, todo, done):
        processed_files = os.listdir('/tmp/%s' % tmp)
        for f in processed_files:
            ftp.rename('%s/%s' % (todo, f), '%s/%s' % (done, f))
        return True
    
    def parse_xml_products(self, f):
        products = []
        product_tags = ['id', 'name', 'list_price', 'ean13', 'categ_id/id', 'taxes_id', 'supplier_taxes_id', 'available_in_pos', 'uom_id/id', 'uom_po_id/id']
        root = etree.parse(f).getroot()
        
        for product in root.iter('product'):
            temp_data = {}
            for item in product:
                if item.tag not in product_tags:
                    product_tags.append(item.tag)
                if type(item.text) is types.NoneType:
                    temp_data[item.tag] = "None"
                else:
                    temp_data[item.tag] = item.text.encode('utf-8')
                
            temp_data['id'] = self.set_external_id(temp_data)
            temp_data['ean13'] = self.set_ean_code(temp_data['eancode'])
            temp_data['name'] = temp_data['omschrijving']
            temp_data['list_price'] = float(temp_data['consumentenprijs'])
            temp_data['categ_id/id'] = "cwa_module.%s" % temp_data['cblcode']
            temp_data['taxes_id'] = 'Verkopen/omzet laag' if temp_data['btw'] == '6' else 'Verkopen/omzet hoog'
            temp_data['supplier_taxes_id'] = 'BTW te vorderen laag (inkopen)' if temp_data['btw'] == '6' else 'BTW te vorderen hoog (inkopen)'
            temp_data['available_in_pos'] = 'false'
            temp_data['uom_id/id'] = uom_translations[temp_data['eenheid']]
            temp_data['uom_po_id/id'] = uom_translations[temp_data['eenheid']]
        
            temp_list = []
            for tag in product_tags:
                try:
                    temp_list.append(temp_data[tag])
                except KeyError:
                    temp_list.append("None")
            products.append(temp_list)
        return products, product_tags
    
    def parse_xml_supplier_info(self, f):
        root = etree.parse(f).getroot()
        supplier_info = []
        supplier_info_tags = ['id', 'name/id', 'product_tmpl_id/id', 'inkoopprijs', 'consumentenprijs', 'bestelnummer']
        
        for product in root.iter('product'):
            temp_data = {'leveranciernummer': '', 'eancode': '', 'bestelnummer': '', 'inkoopprijs': 0.0, 'consumentenprijs': 0.0,}
            for item in product:
                if item.tag == 'leveranciernummer':
                    temp_data['leveranciernummer'] = item.text.encode('utf-8')
                elif item.tag == 'eancode':
                    try:
                        temp_data['eancode'] = item.text.encode('utf-8')
                    except:
                        temp_data['eancode'] = 'None'
                elif item.tag == 'bestelnummer':
                    temp_data['bestelnummer'] = item.text.encode('utf-8')
                elif item.tag == 'inkoopprijs':
                    temp_data['inkoopprijs'] = float(item.text.encode('utf-8'))
                elif item.tag == 'consumentenprijs':
                    temp_data['consumentenprijs'] = float(item.text.encode('utf-8'))
                elif item.tag == 'eenheid':
                    temp_data['eenheid'] = item.text.encode('utf-8')
                    
            ex_id = 'supplier_info_%s_%s' % (temp_data['leveranciernummer'], temp_data['bestelnummer'])
            name = 'cwa_module.supplier_code_%s' % (temp_data['leveranciernummer'])
            temp_data['pid'] = self.set_external_id(temp_data)
            supplier_info.append([ex_id, name, temp_data['pid'], temp_data['inkoopprijs'], temp_data['consumentenprijs'], temp_data['bestelnummer']])
        return supplier_info, supplier_info_tags
                
                
    def set_external_id(self, data):
        if data['eancode'] == 'None':
            return 'product_ex_id_%s_%s' % (data['leveranciernummer'], data['bestelnummer'])
        else:
            return 'product_ex_id_%s_%s' % (data['eancode'], data['eenheid'])
    
    def set_ean_code(self, ean):
        if ean == 'None':
            return 0
        elif ean[:2] == '21' or ean[:2] == '23':
            return sanitize_ean13(ean)
        else:
            if len(str(ean)) < 13:
                return ((13-len(str(ean))) * '0') + ean
            else:
                return ean
            
    def split_data(self, data):
        split_size = 50
        return [data[x:x+split_size] for x in range(0, len(data), split_size)]
        
    def load_records(self, cr, uid, tags, data, model):
        data = self.split_data(data)
        for d in data:
            new_cr = self.pool.cursor()
            x = self.pool.get(model).load(new_cr, uid, tags, d)
            new_cr.commit()
            new_cr.close()
            _logger.error(x)
            #if len(x['messages']) > 0:
            #    _logger.error([x, d])
        return True
    
    def gen_tmp_name(self):
        tmp = 'cwa_import_%s' % datetime.datetime.now().isoformat().replace(':', '').replace('-', '').replace('.', '')
        return tmp

    def write_log(self, log_data):
        with open('error_log.txt', 'a') as f:
            f.write(str(log_data)+'\n\n')
    
    def run(self, cr, uid):
        ''' 
        params[0] = ip address
        params[1] = uid
        params[2] = pwd
        params[3] = todo directory
        params[4] = done directory 
        '''
        _logger.warning("Getting arguments")
        params = self.pool['ir.config_parameter'].get_param(cr, uid, 'cwa.import.ftp_info').split(';')
        _logger.warning(params)
        _logger.warning("Connecting to ftp")
        ftp = self.connect_to_ftp(params[0], params[1], params[2]) # returns ftp connection instance
        tmp = self.gen_tmp_name()
        _logger.warning("Downloading files")
        self.download_ftp_files(tmp, ftp, params[3], params[4])
        self.disconnect_from_ftp(ftp)
        _logger.warning("Parsing files")
        for f in os.listdir('/tmp/%s' % tmp):
            _logger.warning("Parsing products")
            product_info = self.parse_xml_products('/tmp/%s/%s'%(tmp, f))
            _logger.warning("Parsing supplier info")
            supplier_info = self.parse_xml_supplier_info('/tmp/%s/%s'%(tmp, f))
            _logger.warning("Loading products")
            self.load_records(cr, uid, product_info[1], product_info[0], 'product.template')
            _logger.warning("Loading supplierinfo")
            self.load_records(cr, uid, supplier_info[1], supplier_info[0], 'product.supplierinfo')
        _logger.warning("Moving files")
        ftp = self.connect_to_ftp(params[0], params[1], params[2])
        self.move_ftp_files(tmp, ftp, params[3], params[4])
        ftp.quit()
        _logger.warning("Done")
        return True


class extended_supplierinfo(models.Model):
    _inherit = 'product.supplierinfo'
    
    inkoopprijs = fields.Float('inkoopprijs')
    consumentenprijs = fields.Float('consumentenprijs')
    bestelnummer = fields.Integer('bestelnummer')
    
    
class extended_template(models.Model):
    _inherit = 'product.template'

    eancode = fields.Char('eancode')
    omschrijving = fields.Char('omschrijving')
    weegschaalartikel = fields.Char('weegschaalartikel')
    wichtartikel = fields.Char('wichtartikel')
    pluartikel = fields.Char('pluartikel')
    inhoud = fields.Char('inhoud')
    eenheid = fields.Char('eenheid')
    verpakkingce = fields.Char('verpakkingce')
    merk = fields.Char('merk')
    kwaliteit = fields.Char('kwaliteit')
    btw = fields.Char('btw')
    cblcode = fields.Char('cblcode')
    leveranciernummer = fields.Char('leveranciernummer')
    bestelnummer = fields.Char(compute="_compute_bestelnummer")
    sve = fields.Char('sve')
    status = fields.Char('status')
    d204 = fields.Char('d204')
    d209 = fields.Char('d209')
    d210 = fields.Char('d210')
    d212 = fields.Char('d212')
    d213 = fields.Char('d213')
    d214 = fields.Char('d214')
    d234 = fields.Char('d234')
    d215 = fields.Char('d215')
    d239 = fields.Char('d239')
    d216 = fields.Char('d216')
    d217 = fields.Char('d217')
    d217b = fields.Char('d217b')
    d220 = fields.Char('d220')
    d221 = fields.Char('d221')
    d221b = fields.Char('d221b')
    d222 = fields.Char('d222')
    d223 = fields.Char('d223')
    d236 = fields.Char('d236')
    d235 = fields.Char('d235')
    d238 = fields.Char('d238')
    d238b = fields.Char('d238b')
    d225 = fields.Char('d225')
    d226 = fields.Char('d226')
    d228 = fields.Char('d228')
    d230 = fields.Char('d230')
    d232 = fields.Char('d232')
    d237 = fields.Char('d237')
    d240 = fields.Char('d240')
    proefdiervrij = fields.Char('proefdiervrij')
    vegetarisch = fields.Char('vegetarisch')
    veganistisch = fields.Char('veganistisch')
    rauwemelk = fields.Char('rauwemelk')
    inkoopprijs = fields.Float(compute="_compute_inkoopprijs")
    consumentenprijs = fields.Float(compute="_compute_consumentenprijs")
    ingangsdatum = fields.Char('ingangsdatum')
    herkomst = fields.Char('herkomst')
    ingredienten = fields.Char('ingredienten')
    statiegeld = fields.Char('statiegeld')
    kassaomschrijving = fields.Char('kassaomschrijving')
    plucode = fields.Char('plucode')
    
    @api.one
    def _compute_inkoopprijs(self):
        try:
            self.inkoopprijs = self.seller_ids[0].inkoopprijs
        except:
            _logger.warning("Could not set inkoopprijs")

    @api.one        
    def _compute_bestelnummer(self):
        try:
            self.bestelnummer = self.seller_ids[0].bestelnummer
        except:
            _logger.warning("Could not set bestelnummer")

    @api.one       
    def _compute_consumentenprijs(self):
        try:
            self.consumentenprijs = self.seller_ids[0].consumentenprijs
        except:
            _logger.warning("Could not set consumentenprijs")

    
